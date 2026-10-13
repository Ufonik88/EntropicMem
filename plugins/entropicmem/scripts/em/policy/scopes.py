"""§3.5's scoping & visibility resolution (EM-402).

One :class:`ScopeContext` per session, narrowed per turn by
:meth:`ScopeContext.with_author` — the §3.5 shape:

    Resolved once per turn into a
    ScopeContext(profile, user, chat, chat_type, author, is_owner).

The rules, straight from §3.5:

* ``scope_mode`` (config) — ``profile`` (writes ``scope_user=''``, reads all
  memories of the profile, v2 behaviour), ``user`` (**default when a gateway
  ``user_id`` is present**: writes ``scope_user=<author or user_id>`` with
  ``visibility='user'``, reads ``scope_user IN (<current>, '')`` plus the owner
  rule), ``chat`` (``user`` plus ``scope_chat=<chat_id>`` and
  ``visibility='chat'`` for chat-derived facts).
* Local CLI/primary sessions without gateway identity resolve ``user`` to
  ``meta.owner_user_id`` (default ``"owner"``) with ``is_owner=True``. The
  plan names a store ``meta`` key; ``em`` reads no database while resolving a
  scope, so the value is taken from config ``owner_user_id`` instead — the one
  recorded interpretation in this file.
* Group chats: the per-turn author (``on_turn_start``'s ``author_id``) is the
  user bucket for that turn's prefetch and for the attribution of extracted
  memories. **Bot authors never create user-scoped memories** — their writes go
  profile-wide (:meth:`write_scope`).
* The owner rule: ``owner_user_ids`` (config; gateway ids that map to the
  owner). A guest never widens to other users' rows: owner-ness governs
  owner-only *rows* only, exactly as ``em.store.types`` already implements.

Nothing here imports the host, reads ``os.environ``, or touches a database:
``from_init_kwargs`` is handed the host's ``initialize()`` kwargs as plain data.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional, Sequence, Tuple

from ..store.types import Scope

logger = logging.getLogger(__name__)

#: §3.5's ``scope_mode`` values, in table order.
SCOPE_MODES: Tuple[str, ...] = ("profile", "user", "chat")

#: The fallback bucket for a local session without gateway identity. §3.5 calls
#: it ``meta.owner_user_id``; see the module docstring for why it is config.
DEFAULT_OWNER_USER_ID = "owner"

_WARNED_BAD_MODE = False


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _owner_list(config: Mapping[str, Any]) -> Tuple[str, ...]:
    raw = config.get("owner_user_ids") or ()
    return tuple(_clean(u) for u in raw if _clean(u))


def resolve_scope_mode(kw: Mapping[str, Any], config: Mapping[str, Any]) -> str:
    """The ``scope_mode`` this session runs under (§3.5's table).

    Explicit config wins (an invalid value is logged once and ignored);
    otherwise ``user`` when the host delivered a gateway ``user_id`` or
    ``chat_id``, else ``profile`` — the rule that keeps a CLI/primary session
    without gateway identity writing profile-wide, exactly as the provider did
    before EM-402.
    """
    global _WARNED_BAD_MODE
    explicit = _clean(config.get("scope_mode")).lower()
    if explicit:
        if explicit in SCOPE_MODES:
            return explicit
        if not _WARNED_BAD_MODE:
            _WARNED_BAD_MODE = True
            logger.warning(
                "entropicmem: scope_mode %r is not one of %s — using the default",
                explicit,
                "/".join(SCOPE_MODES),
            )
    if _clean(kw.get("user_id")) or _clean(kw.get("chat_id")):
        return "user"
    return "profile"


def _is_owner_for(user: str, owners: Sequence[str]) -> bool:
    """EM-118's rule, unchanged: guests exist only with a non-empty owner list.

    A guest is exactly ``user`` present, ``owner_user_ids`` non-empty, and
    ``user`` not among them. With no list configured nobody is a guest — v2's
    single-pool behaviour — and a profile-wide caller is the owner context.
    """
    return not (user and owners and user not in owners)


@dataclass(frozen=True)
class ScopeContext:
    """§3.5's resolved scope: one per session, narrowed per turn.

    ``user`` is the current bucket — the per-turn author when one is known,
    else the gateway ``user_id``, else the local owner id (``user``/``chat``
    modes) or ``''`` (profile mode). ``author`` is who this turn is attributed
    to, which is not always the bucket (a bot author writes profile-wide).
    """

    profile: str = ""
    user: str = ""
    chat: str = ""
    chat_type: str = ""
    author: str = ""
    #: Owner-ness for the current bucket (EM-118). The **default is True**,
    #: deliberately, and it is not the store's fail-closed ``Scope.is_owner``
    #: default: an empty context is "nothing has been resolved" — the v2
    #: single-owner, profile-wide context the provider ran under before EM-402
    #: — and the pre-EM-402 provider passed ``is_owner=True`` for exactly that
    #: state. Every real path resolves the field (``from_init_kwargs`` at
    #: ``initialize``, ``with_author`` per turn), and owner-ness only ever
    #: governs owner-only *rows*; the user rule that hides one user's rows from
    #: another does not depend on it.
    is_owner: bool = True
    #: The §4.1 author trio's ``is_bot`` for the current turn. Only ever
    #: consumed by :meth:`write_scope` — bot authors never create user-scoped
    #: memories (§3.5).
    author_is_bot: bool = False
    #: The config's ``owner_user_ids``, carried so ``with_author`` can re-derive
    #: ``is_owner`` for a per-turn bucket. Not part of :attr:`scope_key`:
    #: owner-ness is already an input to it.
    owner_user_ids: Tuple[str, ...] = field(default=())

    # -- construction -------------------------------------------------------

    @classmethod
    def from_init_kwargs(
        cls, kw: Mapping[str, Any], config: Mapping[str, Any]
    ) -> "ScopeContext":
        """Resolve the session's scope from ``initialize()`` kwargs + config."""
        mode = resolve_scope_mode(kw, config)
        owners = _owner_list(config)
        user_id = _clean(kw.get("user_id"))
        chat_id = _clean(kw.get("chat_id"))
        chat_type = _clean(kw.get("chat_type"))

        # profile mode is the v2-shaped profile-wide pool; user/chat modes fall
        # back to the local owner bucket without a gateway identity (§3.5's
        # local-CLI bullet).
        if mode == "profile":
            user = ""
        elif user_id:
            user = user_id
        else:
            user = _clean(config.get("owner_user_id")) or DEFAULT_OWNER_USER_ID
        chat = chat_id if mode == "chat" else ""

        if not user_id and mode != "profile":
            # Local CLI/primary session without gateway identity: is_owner=True
            # (§3.5), and the owner list does not apply to the local owner.
            is_owner = True
        else:
            is_owner = _is_owner_for(user_id, owners)
        return cls(
            profile=_clean(kw.get("agent_identity")),
            user=user,
            chat=chat,
            chat_type=chat_type,
            is_owner=is_owner,
            owner_user_ids=owners,
        )

    # -- per turn ----------------------------------------------------------

    def with_author(self, author_id: Any, is_bot: bool = False) -> "ScopeContext":
        """This turn's scope: the author is the user bucket (§3.5, group chats).

        A non-bot author's id becomes the bucket and the attribution for
        extracted memories; ``is_owner`` is re-derived for that bucket from
        ``owner_user_ids``. A **bot** author keeps the same shape — the author
        is still the bucket — but :meth:`write_scope` sends its writes
        profile-wide, because bot authors never create user-scoped memories.
        An absent author leaves the bucket alone; the bot flag still applies to
        writes.
        """
        author = _clean(author_id)
        if not author:
            return replace(self, author="", author_is_bot=bool(is_bot))
        return replace(
            self,
            user=author,
            author=author,
            author_is_bot=bool(is_bot),
            is_owner=_is_owner_for(author, self.owner_user_ids),
        )

    def with_user(self, user: Any, *, owner_user_ids: Optional[Sequence[str]] = None) -> "ScopeContext":
        """Re-bucket to *user*, re-deriving owner-ness.

        The seam older callers (and tests) use when they only have a gateway
        user id; ``from_init_kwargs`` is the real construction path. Pass
        ``owner_user_ids`` to re-derive against a config list the context has
        not carried (the provider's ``_gateway_user_id`` setter does).
        """
        user = _clean(user)
        owners = self.owner_user_ids if owner_user_ids is None else tuple(
            _clean(u) for u in owner_user_ids if _clean(u)
        )
        return replace(
            self,
            user=user,
            owner_user_ids=owners,
            is_owner=_is_owner_for(user, owners),
        )

    # -- derived views -----------------------------------------------------

    @property
    def scope_key(self) -> str:
        """A stable hash of the scope, for caches.

        Stable across processes and runs (sha256 over the identity fields with
        a fixed separator), never ``hash()``. Every field a read rule can depend
        on is included, so two contexts with one key are guaranteed to read the
        same rows — the property the prefetch cache needs before it may reuse
        one author's block for another.
        """
        parts = (
            self.profile,
            self.user,
            self.chat,
            self.chat_type,
            self.author,
            "1" if self.is_owner else "0",
            "1" if self.author_is_bot else "0",
        )
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()

    @property
    def is_guest(self) -> bool:
        """EM-118's guest flag: the bucket is not the owner context.

        ``not is_owner`` — which for an unresolved (default) context is False,
        exactly as the pre-EM-402 ``_is_guest()`` answered for an
        uninitialized provider.
        """
        return not self.is_owner

    def to_scope(self) -> Scope:
        """The read scope every store call is filtered by."""
        return Scope(
            profile=self.profile,
            user=self.user,
            chat=self.chat,
            chat_type=self.chat_type,
            author=self.author,
            is_owner=self.is_owner,
        )

    def write_scope(self) -> Scope:
        """The scope writes are stamped with.

        Identical to :meth:`to_scope` except for a bot-author turn: §3.5's
        "bot authors never create user-scoped memories", satisfied by writing
        the row profile-wide (``scope_user=''``) while keeping the ``author``
        stamp, so the memory is attributed to the bot but belongs to the
        profile.
        """
        scope = self.to_scope()
        if self.author_is_bot:
            return replace(scope, user="", is_owner=False)
        return scope
