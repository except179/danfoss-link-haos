# Independent Danfoss pairing

Only pair a new independent App client with the controller owner's physical
approval. Keep existing phone clients paired. Do not reset the CC or regenerate
identity to troubleshoot an unavailable connection.

After MQTT verification, open **Danfoss pairing**. At the physical Link CC use
**House Control → Settings → Wi-Fi and Apps → App options → Add App → Connect App**
to obtain a fresh cloud App code. Wording varies by firmware/language. Enter
the code in the masked field, approve physical pairing and choose **Pair
independent client**. Local `0000` codes are unsupported.

Follow **Connection diagnostics** while pairing runs. Refreshing status is safe;
do not resubmit a running request or blindly retry an uncertain outcome. In
Setup, use **Verify saved identity** before selecting monitoring. An existing
paired installation must not pair again merely for an update.

A historical post-pairing UI rejection remains open for fresh-controller
validation; saved pairing may still exist despite a rejected/repeated form.
Preserve pending/saved identity and report sanitized outcomes, never codes,
keys or controller certificates. [Full setup guide](../danfoss_link/DOCS.md).
