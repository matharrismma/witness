# The Community — the Fellowship Mesh and the groups

The witness app shows the fellowship by reading the core's community doors (`nh_org/community.py`).
It keeps no social state of its own.

## Read / compose (done)

| call | core door | what it is |
|---|---|---|
| `community.overview()` | `GET /mesh` | the Fellowship Mesh doctrine — what it is, its duty, its roles |
| `community.map(fp="")` | `GET /mesh/map` | the map around a node; with no `fp` the mesh is hidden and the core returns the **gated invitation** (Ask/Seek/Knock), not the map |
| `community.groups()` | `GET /groups` | the study groups, `{groups, total}` |

The mesh is deliberately hidden — the door opens only to one who is seeking the body. The read
surface surfaces whatever the core returns, including that gate, rather than exposing the map to
everyone.

## Signed / consequential writes — a seam, not performed here

| act | core door |
|---|---|
| join the fellowship (birth a node) | `POST /mesh/node` (signed: `public_key`, `confession`, `confession_sig`) |
| post to the mesh | `POST /mesh/post` |
| leave a blessing on a door | `POST /mesh/door` |
| link / tend / invite / redeem | `POST /mesh/link`, `/mesh/tend`, `/mesh/invite`, `/mesh/redeem` |
| create / join / contribute to a group | `POST /groups`, `/group/join`, `/group/contribute` |

These are the member's **own** acts — most signed with their device key, all consequential and
outward-facing. The app never signs for anyone and never posts on anyone's behalf. The doors are
deliberately kept out of `core_client.CORE_DOORS` (`tests/test_community.py` pins that); they cross
the boundary only as the member's own authorized (and, where required, signed) request.
