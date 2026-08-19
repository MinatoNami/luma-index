"""How much of the library disk one account may fill.

`MIN_FREE_DISK_BYTES` already stops the disk being filled; it does not stop one
account being the one that fills it. This is the per-account half of that, and
the two are separate refusals on purpose: running out of disk is an operational
failure everyone shares, while running out of quota is a fact about one library
that says nothing about anyone else's.

**What counts.** The bytes of the distinct files an account's books point at,
including books in the trash.

Distinct, because the same PDF filed in two folders is two books sharing one
blob, and billing it twice would charge for disk nobody used. Not deduplicated
*across* accounts, though: whether your upload is free would then depend on
whether a stranger happened to upload it first, which is both arbitrary and a
disclosure — a file that costs nothing is a file somebody else already has.

Trashed books count because their bytes are still on the disk. That is also
what makes emptying the trash mean something; a trash that costs nothing is one
nobody ever empties.
"""

from __future__ import annotations

from django.conf import settings
from django.db.models import Max, Sum

from .models import BookSource
from .storage import StorageError


class QuotaExceeded(StorageError):
    """Refusing to write, because this account is at its limit.

    A subclass of StorageError so the upload paths that already stop for a full
    disk stop for a full account too, rather than needing a parallel set of
    except clauses that could drift apart.
    """


def limit_for(user) -> int:
    """This account's allowance in bytes, or 0 for unlimited."""
    if getattr(user, "storage_quota_bytes", None) is not None:
        return max(0, int(user.storage_quota_bytes))
    return max(0, int(getattr(settings, "DEFAULT_USER_QUOTA_BYTES", 0)))


def usage_for(user) -> int:
    """Bytes charged to this account, counted once per distinct file."""
    distinct = (
        BookSource.objects.filter(book__owner=user)
        .values("storage_key")
        # Content addressing means one key is one size; Max is how you say
        # "the size that goes with this key" to a GROUP BY.
        .annotate(size=Max("file_size"))
    )
    return distinct.aggregate(total=Sum("size"))["total"] or 0


def remaining_for(user) -> int | None:
    """Bytes still available, or None when the account has no limit."""
    limit = limit_for(user)
    if not limit:
        return None
    return max(0, limit - usage_for(user))


def already_holds(user, storage_key: str) -> bool:
    """Whether this account is already paying for these exact bytes.

    The same PDF filed in two folders is two books over one blob, so the second
    one is free. Knowing that needs the digest, which means the decision can
    only be made after the file has been read — not from its declared size.
    """
    return BookSource.objects.filter(book__owner=user, storage_key=storage_key).exists()


def ensure_room(user) -> None:
    """Refuse an account with nothing left before it uploads anything.

    Worth doing before accepting an archive: a user who is already full should
    learn it now, rather than from four hundred identical per-entry failures.
    """
    if remaining_for(user) != 0:
        return
    raise QuotaExceeded(
        f"You have used all {limit_for(user) // 1024**2} MiB of your storage "
        f"limit. Delete something, or empty your trash, to make room."
    )


def check_quota_for(user, incoming_bytes: int) -> None:
    """Refuse before writing, the same way the disk check does."""
    limit = limit_for(user)
    if not limit:
        return

    used = usage_for(user)
    if used + incoming_bytes <= limit:
        return

    raise QuotaExceeded(
        f"That would put you over your {limit // 1024**2} MiB storage limit: "
        f"{used // 1024**2} MiB is already in use, including anything in your "
        f"trash."
    )
