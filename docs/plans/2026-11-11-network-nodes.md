# Plan: every control point is a node of the network, and a point near a confluence is that confluence

Status: draft for the author's approval. The author's model and answers of 2026-11-11 are
recorded under [The author's decisions](#the-authors-decisions); N1 to N8 turn them into rules,
and the choices the coordinator made where the answers left a detail open say so.

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
- **The names:** A means nothing. The closing section is the lowest point and is `P1`; the
  outlet of the network, which Hydrolog's canvas shows as its end, is `O` instead of `OUT`. The
  ids do not change any computation.
- **A large tributary without a point** that joins a reach between its ends stays in the reach's
  przyrzecze (PROGRESS Next 10.1 is closed by this answer).

## Decisions

### N1. Ids: a control point's node carries the point's id

- The closing section is `P1`; the points the person adds are `P2`, `P3`, …. The front end
  gives the first click `P1` and every later click the first free `P2…`; deleting P1 leaves the
  other points, and the next click places the closing section again as `P1`.
  `NetworkOutlet.id` defaults to `P1` (was `A`); the API still takes any valid id.
- The node of every control point is a junction whose id is the point's id (`P1`, `P7`, …), the
  closing section's too. Junctions made at a confluence without a point are `J1`, `J2`, … (D15's
  order); subcatchments `Z…` and reaches `R…` as before.
- The outlet node of the hand-off is `O` (was `OUT`), fed by the closing section's node.
- A point id equal, without regard to case, to `O`, `OUT` or `[ZRJ]<digits>` is refused (400
  `validation_error`, `invalid_request`, „Identyfikator punktu nie może mieć postaci Z…, R…, J…
  ani O: …”).

Why: the author reads the network by its points; Hydrolog labels nodes by id. `P1` for the lowest
point and `O` for the end make the schematic read `… → P1 → O`. Hydrolog finds the outlet by its
type (`gui/web/src/handoff/*.js` writes `OUT` only into its own one-subcatchment hand-off), and a
junction takes one inflow or more (`Junction.inflow_count = (1, None)`), so Hydrolog needs no
change.

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

A point drawn to a node **is** that node (N4). The response field `at_mouth` is replaced by
`at_node` (the point moved to a node; the panel says „w węźle sieci” instead of „przy ujściu
dopływu”). The amendments of D3 (the junctions where the paths of points merge, the parent's
cell as a confluence of the mouth rule) are superseded: any node of N2 counts, with or without
other points.

### N4. The tree (amends D4)

- Every control point is a node of the tree (N1), whether points lie above it or not.
- A point not at a node splits its river: the element above it (a headwater, or the reach from
  the next node up with its przyrzecze) enters its node; its node enters the next node down by a
  reach with its przyrzecze.
- A point at a node is that confluence: every branch that joins there enters it, the main river
  (N2's larger upstream area) first. A branch without a point is a headwater entering the node
  with no reach; a branch with points enters it through its lowest node and a reach.
- A point off its parent's trunk joins it at the head cell of the trunk unit its path enters, a
  confluence junction `J…` (D4.2, unchanged); a branch of points has its own trunk, by cascade
  (D4, amended 2026-11-11, unchanged).
- A river of `threshold_m2` without a point that joins at a node's cell is a headwater of its
  own entering the node (D5, amended 2026-11-11, unchanged); a river that joins a reach between
  its ends stays in the przyrzecze (the author's answer).

The closing section alone is a network (`points` may be empty, was at least one): at a node,
one headwater per branch into `P1`; elsewhere, one headwater into `P1`.

### N5. Where a node's elements end (amends D5)

A point at a node takes the place of the confluence junction: each branch's element ends at the
outlet cell of its unit above the node, a unit boundary, as at a junction `J…` today; the node's
own cell and the cells that drain into it from the side belong to the element below it (the
przyrzecze of its reach down). No unit is split by a point at a node (D6 applies only to a point
inside a unit), so the preview's outlines beside it are exact. For the closing section at a node
the network ends at those outlets: its own cell and its side cells (part of one unit of 1 ha) lie
outside, as the part of its unit below it lies outside today, and D11 checks the elements
against the sum of the branches. *(Coordinator's choice: the alternative, the point on its cell
with its own cells given to the largest branch as D5's amendment does for A today, splits a unit
by the raster at every node point and marks the outlines approximate.)*

### N6. Two control points on one node (amends D12)

Two points on one cell after N3, in practice two points drawn to one node, are refused
(`network_points_coincide`) with a text that says why the second is not needed: „Punkty P1 i P2
trafiają w ten sam węzeł sieci; P1 już dzieli zlewnię na cieki, które się w nim łączą. Usuń P2
albo przesuń go dalej niż 50 m od węzła.” The author's P1 at A is this case.

### N7. Kinds and names of the elements (amends D14)

Every point is a node, so no subcatchment belongs to a point and the kind `tributary` goes; the
kinds are `headwater` (shown as „Dopływ”) and `intermediate` („Przyrzecze”). Names in the
hand-off: „Dopływ do P7 (ciek główny)” for the main river's headwater into a node, „Dopływ do P7”
for another branch, „Dopływ powyżej J3” into a confluence junction, „Przyrzecze odcinka R4”; a
node's description „Punkt P7 (Paszówka)”, „Przekrój zamykający P1 (Kaczawa)”, „Zbieg: …” as
today. `node_provenance` keeps the words Hydrolog's GUI reads (`handoff/mapping.js`,
`originWords`: `element`, `point`, `reach`, `at_mouth`): a headwater into a point's node has
`element: "headwater"` and `point`, which Hydrolog shows as „dopływ do punktu P7”; `tributary`
and `at_mouth` are no longer written; a point's node (`element` `point` or `outlet`) gets
`at_node: true` when N3 moved it, a key Hydrolog does not read. Nogat's `nogat-handoff/1` does
not constrain these values, so neither Nogat nor Hydrolog changes.

### N8. Ids and order (amends D15)

D15's walk is unchanged; junctions of control points take their points' ids and are not
numbered, so `J…` counts only the confluences without a point; the outlet `O` is last.

## The cases (tests)

`tests/unit/test_network_tree.py`, `test_network_delineation.py`, `test_network_endpoint.py`,
`test_network_preview.py` on the synthetic river network of `tests/fixtures/pipeline_run.py`;
the preview's parity tests run every case below.

| # | Points | Network |
|---|---|---|
| 1 | P1 alone at a confluence | two headwaters → P1 → O, no reach |
| 2 | P1 alone mid-river | one headwater → P1 → O |
| 3 | P2 on the main river between nodes | headwater → P2 → R1 (+ przyrzecze) → P1 |
| 4 | P2 up a tributary | headwater → P2 → R1 → J1 at the tributary's mouth; the main river above J1 a headwater; J1 → R2 → P1 |
| 5 | P2 30 m above a confluence | P2 moves to the node and is it; both branches enter P2; P2 → R1 → P1 |
| 6 | P2 30 m below a confluence | P2 moves up to the node, as 5 |
| 7 | P1 30 m above or below a confluence | P1 moves to the node, as 1 |
| 8 | A point on a tributary of a tributary | the cascade of 4 |
| 9 | P1 at a confluence, P2 7 m above it | `network_points_coincide` with N6's text |
| 10 | ids `J1`, `z3`, `O`, `out` | 400 `invalid_request` |
| 11 | A tributary without a point joining a reach between its ends | stays in the przyrzecze |

The test of D11 (the elements add up to the closing section) and the tree checks of every
network (each reach runs down a main river; no przyrzecze holds a river that joins at a node)
stay.

## Front end and documents

- `js/network.js`: P1 for the first click, `at_node`, a network of the closing section alone
  („Oblicz charakterystyki” enabled with no other point), the labels „Przekrój zamykający P1”,
  „Zlewnia P1 (całość)”, the tree rows of a node entered without a reach („P7 → P1”).
- `index.html`, `js/info-texts.js`, `docs/INFO_TEXTS_SOURCES.md`, the guide's chapter 06 „Sieć
  zlewni”, the presentation: A becomes P1, „przy ujściu” becomes „w węźle”, the closing section at
  a confluence splits it.
- ADR-080 amended (D3, D4, D5, D11, D12, D14, D15); `docs/CHANGELOG.md`, `docs/ARCHITECTURE.md`,
  `docs/COMPUTATION_PIPELINE.md`, `docs/integrations/HYDROLOG.md` (the outlet `O`, node ids of
  points); PROGRESS Next 10.1 closed.

## Stages

1. **S1, the tree and the API** (`core/network_tree.py`, `core/network_delineation.py`,
   `core/network_preview.py`, `core/handoff.py`, `core/messages.py`, `models/schemas.py`,
   `api/endpoints/network.py`, their tests): N1 to N8, cases 1 to 11.
2. **S2, the front end and the documents** (the list above), with a check in the browser at 1440
   and 390 px.
3. **S3, the smoke on kaczawa2**: the author's network without the old P1 gives
   `P1 ← R…, Z…, R…, Z…` (the Nysa Szalona and the Kaczawa), opens in Hydrolog's Sieć with P1 and
   O on the canvas and computes; the old P1 beside the closing section gives N6's refusal.

## Risks

| Risk | Effect | Answer |
|---|---|---|
| At 10 ha a node lies every few hundred metres | a click within 50 m of a gully's mouth makes the point a node with the gully as an element of some 0.1 km² | the person chooses a coarser „Linie spływu” (1 km², 10 km²); the panel shows the node the point moved to |
| The closing section at a node loses its own cell and side cells (N5) | the network's area is up to 1 ha smaller than the accumulation at the click | D11 checks against the branches; „Zlewnia P1 (całość)” is their union |
| `at_mouth`, `tributary` and the ids change in the API | a consumer of the response breaks | the API's network routes have no consumer besides Hydrograf's front end (checked in the workspace's repositories); the hand-off's consumer, Hydrolog's GUI, reads only the provenance words N7 keeps |

## Not in this plan

- The one-subcatchment hand-off of „Wybierz zlewnię” (`Z1 → OUT`), which Hydrolog writes the same
  way: renaming its outlet is a change for both projects.
- A notice of a large tributary inside a przyrzecze (Next 10.1): the author keeps it there.
- The main river by MPHP's hierarchy (the author: a later plan if the network moves to MPHP).
