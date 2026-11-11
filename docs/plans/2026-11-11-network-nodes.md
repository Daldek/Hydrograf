# Plan: every control point is a node of the network, named by where it lies

Approved: 2026-11-11. The author's model and answers are recorded under
[The author's decisions](#the-authors-decisions); N1 to N8 turn them into rules. The details the
answers left open were proposed by the coordinator and approved by the author (N5: variant 1;
N1: the ids by the place of a node, numbered by the network, variant 1); N8's numbering from the
closing section upward is the coordinator's reading of the author's „P1 for the lowest point”.

Requirements: ADR-080 and its plan [`2026-11-10-network-delineation.md`](2026-11-10-network-delineation.md)
(D2 to D5, D11, D12, D14, D15, amended here); ADR-081 and the plan
[`2026-11-11-network-preview.md`](2026-11-11-network-preview.md) (the preview composes the same tree).

## Why

On the author's kaczawa2 network of 2026-11-11 (A at the confluence of the Nysa Szalona and the
Kaczawa, P1 7 m above A on the Nysa Szalona, P2 to P9 at the tributaries' mouths) the hand-off
was `R6 + Z12 → J6 → J10 ← R9 + Z19`:

- P1 and A were nodes `J6` and `J10`; a point's id lived only in a node's description, so
  Hydrolog's canvas, which labels nodes by id, showed neither P1 nor A;
- P1 entered A with no reach (D3, amended), which the map does not draw: the author read it as
  „no connection from P1 to A”;
- P1 was clicked only to split A's catchment into the Kaczawa and the Nysa Szalona. Without P1
  the same network is `A ← R6, Z12, R9, Z19`, which is what the author expected: a closing
  section at a confluence already splits its catchment, so the second point was redundant, and
  nothing said so.

## The author's decisions

The author's model (2026-11-11), in his words reduced to rules:

1. The closing section is placed on the network; at a confluence of two rivers it splits its
   catchment into the two rivers at once, each entering it with no reach.
2. A point on a river splits it into an upper and a lower part. On a tributary, a node is made
   where the tributary meets the main river.
3. A point near a node of the network is drawn to the node: the node splits into the elements
   above it, and the stretch below it is the przyrzecze of the reach below.
4. On a tributary of a tributary the tributary is the main river, and so on, by cascade.
5. A river that joins the closing section and is not divided enters it with no reach; a
   divided one enters it through its lowest node and a reach, and further divisions make further
   nodes and reaches.

His answers to the coordinator's questions:

- **The node of the network** is a confluence of the streams of the threshold of „Linie spływu”
  chosen on the map (the request's `threshold_m2`, the network the points already snap to).
- **The tolerance** of 50 m applies upward too (a point just below a confluence), and to the
  closing section.
- **Two points on one node** do not arise in his model: a closing section at a confluence
  already splits it, so a second point there should not be made.
- **The main river** at a confluence stays the one of the larger upstream area
  (`trace_main_channel`, ADR-046), as the network is built on flow lines; MPHP's hierarchy would
  be another plan.
- **The names:** A means nothing. A node's id says where it lies, not who placed it: `J` is
  always a confluence (a point drawn to one, the closing section at one, or a junction the
  network makes), `P` only a point on a river away from a confluence. The ids follow the network,
  numbered without gaps, and the map labels each point by its node's id after every preview
  (variant 1 of two: the other kept the number of the click and left gaps). The outlet of the
  network, which Hydrolog's canvas shows as its end, is `O` instead of `OUT`. The ids change no
  computation.
- **The cells at a node** (N5): variant 1.
- **A large tributary without a point** that joins a reach between its ends stays in the reach's
  przyrzecze (PROGRESS Next 10.1 is closed by this answer).

## Decisions

### N1. Ids: a node is `J` at a confluence and `P` elsewhere

- Every node of the network has an id made by the network (N8), never the request's: `J<n>` for
  a node at a confluence (N2), whoever placed it, `P<n>` for a control point away from one,
  `Z<n>` subcatchments, `R<n>` reaches, and `O` the outlet (was `OUT`), fed by the closing
  section's node.
- The ids of the request (`NetworkPoint.id`, `NetworkOutlet.id`) are the client's handles of its
  points: unique, of D12's pattern, and they never reach the hand-off. The response gives each
  point its `node`; the problem documents name a point by its handle (`point_id`) as today.
  `NetworkOutlet.id` loses its default `A` and is required.
- A point's name (optional, as today) goes into the description of its node and of the elements
  named after it.

Why: the author reads the schematic by its geometry: a `J` is where rivers meet, a `P` where a
river is divided. Hydrolog labels nodes by id, finds the outlet by its type (`gui/web/src/handoff/*.js`
writes `OUT` only into its own one-subcatchment hand-off) and takes a junction of one inflow or
more (`Junction.inflow_count = (1, None)`), so Hydrolog needs no change. With the handles kept
out of the hand-off no id of the request can collide with an id of the network.

### N2. The nodes of the network

A node of the hydrographic network is a stream cell of `threshold_m2` into which two or more
streams of `threshold_m2` drain: the head cell of a unit at which two or more units whose
upstream area reaches `threshold_m2` end (`_Catchment.above`, `accumulation_km2`). The units of
1 ha that join there below the threshold do not make a node.

### N3. Drawing a point to a node (replaces D3)

After D2's snapping every control point, the closing section included, moves to the nearest node
along the stream within `MOUTH_TOLERANCE_M` = 50 m:

- downward: the first node on its flow path, at most 50 m of flow distance below it;
- upward: the head cell of its own unit when that cell is a node at most 50 m of flow distance
  above it (a point on the merged river just below a confluence);
- both within 50 m: the nearer by flow distance, the lower one on a tie.

A point drawn to a node **is** that node (N4) and its id is a `J`. The response field `at_mouth`
is replaced by `at_node` (the point moved to a node; the panel says „w węźle sieci” instead of
„przy ujściu dopływu”). The amendments of D3 (the junctions where the paths of points merge, the
parent's cell as a confluence of the mouth rule) are superseded: any node of N2 counts, with or
without other points.

### N4. The tree (amends D4)

- Every control point is a node of the tree, whether points lie above it or not.
- A point not at a node (a `P`) splits its river: the element above it (a headwater, or the reach
  from the next node up with its przyrzecze) enters it; it enters the next node down by a reach
  with its przyrzecze.
- A point at a node (a `J`) is that confluence: every branch that joins there enters it, the main
  river (N2's larger upstream area) first. A branch without a point is a headwater entering the
  node with no reach; a branch with points enters it through its lowest node and a reach.
- A point off its parent's trunk joins it at the head cell of the trunk unit its path enters, a
  confluence: a `J` the network makes (D4.2, unchanged); a branch of points has its own trunk, by
  cascade (D4, amended 2026-11-11, unchanged).
- A river of `threshold_m2` without a point that joins at a node's cell is a headwater of its
  own entering the node (D5, amended 2026-11-11, unchanged); a river that joins a reach between
  its ends stays in the przyrzecze (the author's answer).

The closing section alone is a network (`points` may be empty, was at least one): at a node, one
headwater per branch into its `J`; elsewhere, one headwater into its `P`.

### N5. Where a node's elements end (amends D5)

A point at a node takes the place of the confluence junction: each branch's element ends at the
outlet cell of its unit above the node, a unit boundary, as at a confluence junction today; the
node's own cell and the cells that drain into it from the side belong to the element below it
(the przyrzecze of its reach down). No unit is split by a point at a node (D6 applies only to a
point inside a unit), so the preview's outlines beside it are exact. For the closing section at
a node the network ends at those outlets: its own cell and its side cells (part of one unit of
1 ha) lie outside, as the part of its unit below it lies outside today, and D11 checks the
elements against the sum of the branches. *(The author chose this variant on 2026-11-11 over the
alternative, the point on its cell with its own cells given to the largest branch as D5's
amendment does for A today, which splits a unit by the raster at every node point and marks the
outlines approximate; the difference is under 1 ha.)*

### N6. Two control points on one node (amends D12)

Two points on one cell after N3, in practice two points drawn to one node, are refused
(`network_points_coincide`, `point_ids` the handles) with a text that says why the second is not
needed: „Punkty {point_ids} trafiają w ten sam węzeł sieci: jeden punkt w węźle już dzieli
zlewnię na cieki, które się w nim łączą. Usuń jeden z nich albo przesuń go dalej niż 50 m od
węzła.” The author's P1 beside A is this case.

### N7. Kinds and names of the elements (amends D14)

Every point is a node, so no subcatchment belongs to a point and the kind `tributary` goes; the
kinds are `headwater` (shown as „Dopływ”) and `intermediate` („Przyrzecze”). Names in the
hand-off: „Dopływ do J4 (ciek główny)” for the main river's headwater into a node, „Dopływ do
J4” for another branch, „Dopływ do P3” above a `P`, „Przyrzecze odcinka R4”. A node's
description says what it is and the name of its point, if any: „Zbieg: Paszówka” (a point drawn
to a confluence), „Zbieg” (a confluence the network made), „Punkt: Nysa Mała” (a `P`),
„Przekrój zamykający: Kaczawa” (the closing section, at a confluence or not).

`node_provenance` keeps the words Hydrolog's GUI reads (`handoff/mapping.js`, `originWords`:
`element`, `point`, `reach`, `at_mouth`): a headwater into a node of a person's point has
`element: "headwater"` and `point` = that node's id, which Hydrolog shows as „dopływ do punktu
J4”; `tributary` and `at_mouth` are no longer written. A node keeps `element` (`confluence`,
`point`, `outlet`), adds `name` when its point has one, and `at_node: true` when N3 moved it;
Hydrolog does not read the two new keys. Nogat's `nogat-handoff/1` does not constrain these
values, so neither Nogat nor Hydrolog changes.

### N8. Ids and order (amends D15)

The hand-off still lists the nodes in D15's order (each after every node it receives). The
numbers are given by a walk from the closing section upward, each node before the branches it
receives (the trunk first, then by descending accumulation of their last cell, D15), each kind
counted on its own: the closing section is `J1` or `P1`, and the numbers grow upstream, so the
schematic reads from its end. The same points in any order still give the same ids.

## The cases (tests)

`tests/unit/test_network_tree.py`, `test_network_delineation.py`, `test_network_endpoint.py`,
`test_network_preview.py` on the synthetic river network of `tests/fixtures/pipeline_run.py`;
the preview's parity tests run every case below. „CS” is the closing section.

| # | Points | Network |
|---|---|---|
| 1 | CS alone at a confluence | two headwaters → J1 → O, no reach |
| 2 | CS alone mid-river | one headwater → P1 → O |
| 3 | CS mid-river, a point on the main river between nodes | headwater → P2 → R1 (+ przyrzecze) → P1 |
| 4 | CS mid-river, a point up a tributary | headwater → P2 → R2 → J1 at the tributary's mouth; the main river above J1 a headwater; J1 → R1 → P1 |
| 5 | a point 30 m above a confluence | it moves to the node and is a `J`; both branches enter it; its reach down to the CS |
| 6 | a point 30 m below a confluence | it moves up to the node, as 5 |
| 7 | CS 30 m above or below a confluence | it moves to the node, as 1 |
| 8 | a point on a tributary of a tributary | the cascade of 4 |
| 9 | CS at a confluence, a point 7 m above it | `network_points_coincide` with N6's text |
| 10 | the handles `J1`, `Z3`, `O`, `x` instead of `P…` | the same network ids as with any other handles |
| 11 | a tributary without a point joining a reach between its ends | stays in the przyrzecze |
| 12 | the points of 4 added in another order | the same ids |

The test of D11 (the elements add up to the closing section) and the tree checks of every
network (each reach runs down a main river; no przyrzecze holds a river that joins at a node)
stay.

## Front end and documents

- `js/network.js`: the first click is the closing section and every later click a point; each
  marker shows its node's id from the latest preview (`points[].node`), and a marker not yet in
  a preview the first free `P<n>` among the shown ids, which is also its handle in the request,
  so a problem names it as the map does; the panel lists the closing section first, then the
  points by their ids, each with its name field and „w węźle sieci” when `at_node`. A network of
  the closing section alone („Oblicz charakterystyki” enabled with no other point). The labels
  „Przekrój zamykający”, „Zlewnia (całość)” without A, and the tree rows of a node entered without
  a reach („J4 → J1”).
- `index.html`, `js/info-texts.js`, `docs/INFO_TEXTS_SOURCES.md`, the guide's chapter 06 „Sieć
  zlewni”, the presentation: A goes, `J` and `P` as N1 says them, „przy ujściu” becomes „w
  węźle”, the closing section at a confluence splits it.
- ADR-080 amended (D3, D4, D5, D11, D12, D14, D15); `docs/CHANGELOG.md`, `docs/ARCHITECTURE.md`,
  `docs/COMPUTATION_PIPELINE.md`, `docs/integrations/HYDROLOG.md` (the outlet `O`, the ids of
  nodes); PROGRESS Next 10.1 closed.

## Stages

1. **S1, the tree and the API** (`core/network_tree.py`, `core/network_delineation.py`,
   `core/network_preview.py`, `core/handoff.py`, `core/messages.py`, `models/schemas.py`,
   `api/endpoints/network.py`, their tests): N1 to N8, cases 1 to 12.
2. **S2, the front end and the documents** (the list above), with a check in the browser at 1440
   and 390 px.
3. **S3, the smoke on kaczawa2**: the author's network without the old P1 gives the closing
   section `J1 ← R…, Z…, R…, Z…` (the Nysa Szalona and the Kaczawa), every point at a tributary's
   mouth a `J`, the point up the Nysa Mała a `P` above a `J` at its mouth; it opens in Hydrolog's
   Sieć with those ids and `O` on the canvas and computes; the old P1 beside the closing section
   gives N6's refusal.

## Risks

| Risk | Effect | Answer |
|---|---|---|
| At 10 ha a node lies every few hundred metres | a click within 50 m of a gully's mouth makes the point a node with the gully as an element of some 0.1 km² | the person chooses a coarser „Linie spływu” (1 km², 10 km²); the panel shows the node the point moved to |
| The ids follow the network | adding a point can renumber the markers (J4 becomes J5) | the author's choice; the names of the points stay, and the map, the panel and the hand-off always agree |
| The closing section at a node loses its own cell and side cells (N5) | the network's area is up to 1 ha smaller than the accumulation at the click | D11 checks against the branches; „Zlewnia (całość)” is their union |
| `at_mouth`, `tributary` and the ids change in the API | a consumer of the response breaks | the API's network routes have no consumer besides Hydrograf's front end (checked in the workspace's repositories); the hand-off's consumer, Hydrolog's GUI, reads only the provenance words N7 keeps |

## Not in this plan

- The one-subcatchment hand-off of „Wybierz zlewnię” (`Z1 → OUT`), which Hydrolog writes the same
  way: renaming its outlet is a change for both projects.
- A notice of a large tributary inside a przyrzecze (Next 10.1): the author keeps it there.
- The main river by MPHP's hierarchy (the author: a later plan if the network moves to MPHP).
