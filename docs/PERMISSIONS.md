# Permissions

Who can do what, and how that answer is arrived at. Two screens sit over one
model: **Permissions** is what each *role* may do; **Exceptions** is where one
*person* differs from their role.

`backend/permissions.py` is the whole model. Read it before changing anything
here — a mistake in authorisation is silent: nothing errors, the wrong person
simply can do something.

## The shape of a permission

A permission is a string, `<entity>:<action>`:

```
customers:read   customers:create   customers:update   customers:delete   customers:remark
```

Actions are `read · create · update · delete · remark`. `remark` is separate
from `update` on purpose: an advisor should be able to add to a record's history
without being able to alter the record.

The catalogue is **derived from the entity registry**, so a new entity is
automatically covered rather than accidentally unprotected. 34 entities × 5
actions = 170 codes today.

## How an answer is reached

```
        role grants                    person's exceptions            what the routes enforce
  ┌───────────────────────┐          ┌─────────────────────┐         ┌──────────────────────┐
  │  code patterns   OR   │  ──────► │  inherit → no row   │  ─────► │  permissions_for()   │
  │  saved matrix rows    │          │  allow   → add      │         │  cached on the user  │
  └───────────────────────┘          │  deny    → remove   │         └──────────────────────┘
                                     └─────────────────────┘
```

**1. Role grants.** Two possible sources, and which one wins is the entire point
of the `permission_policy` table:

* **Nobody has saved the Permissions screen yet** → the wildcard patterns in
  `ROLES` in `backend/permissions.py`. A grant change ships with a deploy rather
  than needing a data migration. This is where every organisation starts.
* **Somebody has saved it** → the `role_permissions` rows. The screen says it
  becomes the authority, and silently ignoring it would be a lie.

**2. That person's exceptions**, from `user_permission_overrides`:

| stored | meaning |
|---|---|
| *no row* | inherit — the role decides. The normal case, and why the table stays small. |
| `allow` | held, even if the role does not grant it |
| `deny` | not held, even if the role does grant it |

**Deny beats allow.** The reason to write a deny is to take something away from
someone whose role hands it out; a rule that loses to the thing it exists to
override is not a rule.

## Why resolution happens at authentication

Every route checks access with `permissions.require(current_user, ...)`, which
has **no database session**. So the effective set is resolved once in
`auth.get_current_user` and cached on the user for the rest of the request.

This is load-bearing, not an optimisation. Without it, an exception or a saved
matrix would render correctly in the UI and be **ignored by the routes that
enforce it** — a deny you can see but that does not apply, which is worse than
no deny at all. Doing it at authentication means every existing call site picks
it up with no change, and none can be forgotten.

`permissions_for(user)` therefore prefers the cached set; passing `db` explicitly
recomputes, which is what the admin screens do when previewing somebody else.

## The rails that stop a lockout

Removing the permission that opens the Permissions screen **cannot be undone
from inside the app** — the permission needed to grant it back is the one being
removed. Three things prevent that:

1. **`ADMIN_FLOOR`.** An Admin always keeps `permissions:update`,
   `permissions:read`, `users:read`, `users:update` and `roles:read`, whatever
   the grid or an exception says. Admin is the role that repairs a mistake.
   The UI renders those ticks locked; the API restores them silently rather than
   rejecting, because a payload without them is a stale client, not an intent.
2. **`refuse_if_locking_everyone_out()`** runs *before* a save is committed,
   against the **proposed** state. If no **active** user would still hold
   `permissions:update`, the save is refused with a 400. A disabled user does not
   count — somebody who cannot sign in cannot rescue anyone.
3. **The creator of a TabDesk table** is a separate, similar rail; see
   `docs/TABDESK.md`.

Note the consequence: while an active Admin exists you *cannot* orphan the
screen, because the floor holds. The guard exists for organisations with no
active Admin.

## Seeding, and the deploy-day trap

`permissions.seed()` runs on every boot. It rebuilds the code catalogue — so a
retired code disappears rather than lingering — and normally re-applies the
`ROLES` patterns to each role.

**Once the policy is custom it stops touching grants.** Re-applying the patterns
would revert every edit on the next deploy, silently, because nobody connects a
deploy with their permissions changing. Roles are still *created* if missing, and
a role created after the matrix was customised is seeded from code once —
otherwise it would exist with no grants at all, which reads as "this role can do
nothing".

## The API

```
GET    /api/permissions/matrix               the grid: roles x codes, plus `custom` and `locked`
PUT    /api/permissions/matrix               save it — {role_name: [codes]}; first save flips `custom`
GET    /api/permissions/exceptions           everyone, with a count of their exceptions
GET    /api/permissions/exceptions/{user_id} one person: role grants, their effects, and what it resolves to
PUT    /api/permissions/exceptions/{user_id} replace them — {code: 'allow'|'deny'|'inherit'}
```

`GET .../exceptions/{user_id}` returns `effective` computed by the **same
function the routes enforce with**, so the screen cannot disagree with reality.
That is deliberate: a permissions screen that reasons about the answer
independently will eventually be wrong, and being wrong here is invisible.

Both writes are audited, and both go through the lockout guard.

## What a 403 tells you

The message distinguishes a role that never granted something from an exception
that took it away:

> You have a permission exception that blocks 'view Audit log'. Your role
> (Partner) would otherwise allow it — ask an admin to check Exceptions.

Without that, an admin asked *"why can't Nishant see the audit log?"* reads the
Partner role, finds that it **does** allow it, and has nowhere left to look.

## Limitations

* **Per-entity, not per-record.** `customers:update` means all customers. There
  is no "only their own customers" — TabDesk has a narrow version of that for its
  own tables (`contributor` edits only rows it created) and nothing else does.
* **No time-bound exceptions.** An exception lasts until somebody removes it.
* **No approval flow.** Anyone with `permissions:update` can change any grant.
* **Roles are still defined in code by default.** The screen mirrors them until
  the first save; there is no UI for creating a *new* role's pattern set, only
  for editing grants once they exist.
