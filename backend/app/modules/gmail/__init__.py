"""Gmail import (fetch-only).

Read-only by construction: the only scope ever requested is gmail.readonly and the
only Gmail calls are profile, messages.list, messages.get and attachments.get.
Fetched emails land in the Inbox. Transaction alert emails are read into a
suggestion that pre-fills the transaction form — nothing is saved automatically.
"""
