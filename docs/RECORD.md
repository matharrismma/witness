# The Record — the witness keeps the testimony

"The library lives on .com — cards, the corpus, the engine; the **RECORD lives on .org** — seals and
badges." The Record surface (`nh_org/record.py`) reads and composes the core's record doors. It holds
no record of its own and signs nothing.

## Read / compose (done)

| call | core door | what it is |
|---|---|---|
| `record.fetch(hash)` | `GET /seal?hash=` | the sealed receipt for a hash — re-checkable testimony, or `None` |
| `record.recent()` | `GET /seals` | the ledger tally (minted, verified, …) |
| `record.badge(hashes)` | `POST /badges` | compose sealed checks into the **evidence** badge, issued **unsigned** |

A seal is minted by the engine when it verifies (`/verify?seal=1`); the receipt is PII-free and lives
at `narrowhighway.org/s/<hash>`. The Record surface is how the witness app reads and re-checks it.

## Signed writes — a seam, not performed here

A **profession of faith**, a **self-attestation**, and **binding a badge to an identity** are the
holder's own signed acts. They require a private key born and kept on the holder's device
(the core's `identity_create`, Ed25519 from four verses) and a signature over the content:

| act | core door | payload |
|---|---|---|
| profess | `POST /mesh/node` | `{public_key, confession, confession_sig}` |
| self-attest | `POST /self-attest` | the holder's own words, signed |
| bind a badge | `POST /attest` | the badge's `content_hash`, signed |

**The app never holds a private key, never signs for anyone, and never rolls crypto.** These doors
are deliberately *not* in `core_client.CORE_DOORS` (`tests/test_record.py` pins that). They cross the
boundary only as the holder's own signed request, carrying their explicit authorization — the client
would pass an already-signed payload through, never produce the signature. Confession is with the
mouth, in one's own words (Romans 10:9-10); never coerced, never generated for anyone.
