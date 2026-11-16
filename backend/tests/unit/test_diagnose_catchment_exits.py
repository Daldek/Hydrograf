"""scripts.diagnose_catchment_exits finds where the D8 flow leaves a polygon.

Tiny synthetic windows of pyflwdir D8 codes (1 E, 2 SE, 4 S, 8 SW, 16 W, 32 NW, 64 N,
128 NE; 0 a pit, 247 no data), the polygon a block of cells, the receivers an index
per cell (1 the polygon itself, 2 and 3 its neighbours).
"""

import numpy as np

from scripts.diagnose_catchment_exits import (
    NODATA,
    OUTFLOW,
    PIT,
    polygon_exits,
    reenters,
)

E, S, W = 1, 4, 16


def _window(shape, rows, cols):
    """D8 all south, the polygon the block rows x cols, catchment 2 around it."""
    d8 = np.full(shape, S, dtype=np.uint8)
    member = np.zeros(shape, dtype=bool)
    member[rows, cols] = True
    receivers = np.where(member, 1, 2).astype(np.int32)
    return d8, member, receivers


def test_a_watershed_drains_through_its_outlet_only():
    d8, member, receivers = _window((5, 5), slice(1, 4), slice(1, 4))
    d8[1:4, 1] = E
    d8[1:4, 3] = W

    exits, _ = polygon_exits(d8, member, receivers, outlet=(3, 2))

    assert len(exits) == 1
    (only,) = exits
    assert (only.kind, only.receiver, only.cell) == (OUTFLOW, 2, (3, 2))
    assert (only.upstream_cells, only.boundary_cells, only.is_outlet) == (9, 1, True)


def test_the_area_of_a_side_exit_is_counted_with_its_receiver():
    # Column 1 drains west into catchment 2, columns 2-4 east into catchment 3
    d8, member, receivers = _window((5, 6), slice(1, 4), slice(1, 5))
    receivers[:, 5] = 3
    d8[1:4, 1] = W
    d8[1:4, 2:5] = E

    exits, drained = polygon_exits(d8, member, receivers, outlet=(1, 4))

    assert [(e.receiver, e.upstream_cells, e.boundary_cells) for e in exits] == [
        (3, 9, 3),
        (2, 3, 3),
    ]
    assert [e.is_outlet for e in exits] == [True, False]
    # Each cell of the polygon is labelled with the number of its exit
    expected = np.zeros(member.shape, dtype=int)
    expected[1:4, 2:5] = 1
    expected[1:4, 1] = 2
    np.testing.assert_array_equal(drained, expected)


def test_inflow_from_outside_is_not_counted():
    d8, member, receivers = _window((6, 5), slice(2, 5), slice(1, 4))
    # The two rows above flow south into the polygon
    d8[2:5, 1] = E
    d8[2:5, 3] = W

    exits, _ = polygon_exits(d8, member, receivers, outlet=(4, 2))

    assert [(e.upstream_cells, e.is_outlet) for e in exits] == [(9, True)]


def test_exit_cells_are_split_by_destination_and_joined_diagonally():
    d8, member, receivers = _window((6, 6), slice(1, 5), slice(1, 5))
    member[4, 4] = False  # a corner of catchment 2: the boundary is a staircase
    receivers[4, 4] = 2
    d8[1:5, 1:5] = E  # every row leaves east
    receivers[1:3, 5] = 3  # rows 1-2 go to catchment 3, rows 3-4 to 2

    exits, _ = polygon_exits(d8, member, receivers, outlet=(1, 4))

    # (3, 4) and (4, 3) touch at a corner and form one exit
    assert [(e.receiver, e.boundary_cells, e.upstream_cells) for e in exits] == [
        (3, 2, 8),
        (2, 2, 7),
    ]


def test_flow_into_no_data_and_into_a_pit_are_their_own_exits():
    d8, member, receivers = _window((5, 5), slice(1, 4), slice(1, 4))
    d8[1:4, 1:4] = E
    d8[1, 4] = 247  # row 1 leaves into a cell without data
    d8[3, 2] = 0  # (3, 1) ends in a pit inside the polygon

    exits, _ = polygon_exits(d8, member, receivers, outlet=(2, 3))

    by_kind = {e.kind: (e.receiver, e.upstream_cells, e.cell) for e in exits}
    # (3, 3), below the pit, leaves beside (2, 3) into catchment 2: one exit
    assert by_kind == {
        OUTFLOW: (2, 4, (2, 3)),
        NODATA: (0, 3, (1, 3)),
        PIT: (0, 2, (3, 2)),
    }
    assert sum(e.upstream_cells for e in exits) == member.sum()


def test_flow_that_comes_back_into_the_polygon_is_told_apart():
    d8, member, _ = _window((5, 6), slice(1, 4), slice(1, 5))
    member[2, 3] = False  # a notch of another catchment in the polygon
    d8[1:4, 1:5] = E  # the notch drains back into the polygon

    assert reenters(d8, member, (2, 2))
    assert not reenters(d8, member, (2, 4))
