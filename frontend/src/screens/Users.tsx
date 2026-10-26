import { useCallback, useState, type FormEvent } from 'react'
import { ApiError, api } from '../api/client'
import type { Member, Role, UserOut } from '../api/types'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { useToast } from '../components/toastContext'
import { Badge, Card, Field, Modal, PageHeader, SkeletonList } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { ROLE_LABEL, useAuth } from '../lib/auth'
import { formatDate } from '../lib/format'
import { newUserErrors, type NewUser } from '../lib/forms'
import { t } from '../strings'
import styles from './Tables.module.css'

const U = t.users
const ROLES: Role[] = ['officer', 'admin', 'member']
export function Users() {
  const load = useCallback(() => Promise.all([api.users(), api.members(undefined, 500)]), [])
  const { data, error, reload, setData } = useLoad(load)
  const { user: me } = useAuth()
  const [creating, setCreating] = useState(false)
  const [managing, setManaging] = useState<UserOut | null>(null)
  const [users, members] = data ?? [null, []]

  const replace = (u: UserOut) => {
    if (!data) return
    const exists = data[0].some((x) => x.id === u.id)
    setData([exists ? data[0].map((x) => (x.id === u.id ? u : x)) : [...data[0], u].sort((a, b) => a.username.localeCompare(b.username)), data[1]])
    setManaging((m) => (m && m.id === u.id ? u : m))
  }

  return (
    <>
      <PageHeader title={U.title} lead={U.lead}
                  actions={<button type="button" className="btn btn-primary" onClick={() => setCreating(true)}><Icon name="plus" /> {U.add}</button>} />
      {error && <ErrorNotice doing={U.loadFailed} error={error} onRetry={reload} />}
      <Card>
        {!users && !error && <SkeletonList what={U.title} />}
        {users && (
          <div className={`table-wrap ${styles.stack}`}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{U.username}</th>
                  <th scope="col">{U.role}</th>
                  <th scope="col">{U.email}</th>
                  <th scope="col">{U.member}</th>
                  <th scope="col">{U.status}</th>
                  <th scope="col">{U.created}</th>
                  <th scope="col"><span className="visually-hidden">{U.actions}</span></th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td><strong>{u.username}</strong>{me?.username === u.username && <span className="subtle"> ({U.you})</span>}</td>
                    <td data-label={U.role}><Badge tone={u.role === 'admin' ? 'attention' : u.role === 'member' ? 'info' : 'low'}>{ROLE_LABEL[u.role]}</Badge></td>
                    <td data-label={U.email}>{u.email ?? <span className="subtle">—</span>}</td>
                    <td data-label={U.member} className={styles.mono}>{u.member_no ?? <span className="subtle">—</span>}</td>
                    <td data-label={U.status}>{u.is_active ? <Badge tone="low" icon="check">{U.active}</Badge> : <Badge tone="high">{U.inactive}</Badge>}</td>
                    <td className="num" data-label={U.created}>{formatDate(u.created_at)}</td>
                    <td className="right">
                      <button type="button" className="btn btn-secondary btn-sm" onClick={() => setManaging(u)} aria-label={U.manage(u.username)}>
                        <Icon name="edit" size={16} /> {t.common.edit}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <CreateUser open={creating} members={members} onClose={() => setCreating(false)} onCreated={(u) => { replace(u); setCreating(false) }} />
      {managing && <ManageUser user={managing} members={members} self={me?.username === managing.username}
                               onClose={() => setManaging(null)} onChanged={replace} />}
    </>
  )
}

function MemberSelect({ id, value, onChange, members, props }: {
  id: string; value: string; onChange: (v: string) => void; members: Member[]
  props?: { 'aria-invalid'?: true; 'aria-describedby'?: string }
}) {
  return (
    <select id={id} className="select" value={value} onChange={(e) => onChange(e.target.value)} {...props}>
      <option value="">{U.chooseMember}</option>
      {members.map((m) => <option key={m.id} value={m.id}>{m.full_name} ({m.member_no})</option>)}
    </select>
  )
}

function CreateUser({ open, members, onClose, onCreated }: {
  open: boolean; members: Member[]; onClose: () => void; onCreated: (u: UserOut) => void
}) {
  const toast = useToast()
  const empty: NewUser = { username: '', password: '', role: 'officer', email: '', member_id: '' }
  const [u, setU] = useState<NewUser>(empty)
  const [tried, setTried] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const errors = tried ? newUserErrors(u) : {}
  const put = (k: keyof NewUser, v: string) => setU((x) => ({ ...x, [k]: v }))

  async function submit(e?: FormEvent) {
    e?.preventDefault()
    setTried(true)
    if (Object.keys(newUserErrors(u)).length) return
    setBusy(true)
    setError(null)
    try {
      const out = await api.createUser({ username: u.username.trim(), password: u.password, role: u.role,
        email: u.email.trim() || null, member_id: u.role === 'member' && u.member_id ? Number(u.member_id) : null })
      toast(U.created_(out.username))
      setU(empty)
      setTried(false)
      onCreated(out)
    } catch (err) {
      setError(err as ApiError)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} title={U.createTitle} onClose={onClose}
           actions={<>
             <button type="button" className="btn btn-quiet" onClick={onClose}>{t.common.cancel}</button>
             <button type="button" className="btn btn-primary" onClick={() => submit()} disabled={busy}>
               {busy && <span className="spinner" aria-hidden />} {U.create}
             </button>
           </>}>
      <form className={styles.modalForm} onSubmit={submit} noValidate>
        <Field id="nu-username" label={U.username} hint={U.usernameHint} error={errors.username}>
          {(p) => <input {...p} className="input" value={u.username} autoComplete="off" onChange={(e) => put('username', e.target.value)} />}
        </Field>
        <Field id="nu-password" label={U.password} hint={U.passwordHint} error={errors.password}>
          {(p) => <input {...p} className="input" type="password" value={u.password} autoComplete="new-password" onChange={(e) => put('password', e.target.value)} />}
        </Field>
        <Field id="nu-role" label={U.role}>
          {(p) => (
            <select {...p} className="select" value={u.role} onChange={(e) => put('role', e.target.value)}>
              {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </select>
          )}
        </Field>
        {u.role === 'member' && (
          <Field id="nu-member" label={U.member} hint={U.memberHint} error={errors.member_id}>
            {(p) => <MemberSelect id={p.id} value={u.member_id} onChange={(v) => put('member_id', v)} members={members.filter((m) => !m.user_id)} props={p} />}
          </Field>
        )}
        <Field id="nu-email" label={U.email} hint={U.emailHint} error={errors.email} optional>
          {(p) => <input {...p} className="input" type="email" value={u.email} autoComplete="off" onChange={(e) => put('email', e.target.value)} />}
        </Field>
        {error && <ErrorNotice doing={U.failed} error={error} />}
        <button type="submit" hidden />
      </form>
    </Modal>
  )
}

function ManageUser({ user, members, self, onClose, onChanged }: {
  user: UserOut; members: Member[]; self: boolean; onClose: () => void; onChanged: (u: UserOut) => void
}) {
  const toast = useToast()
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState(user.email ?? '')
  const [memberId, setMemberId] = useState(user.member_id ? String(user.member_id) : '')

  async function run(what: string, call: () => Promise<UserOut>, done: string) {
    setBusy(what)
    setError(null)
    try {
      onChanged(await call())
      toast(done)
      if (what === 'password') setPassword('')
    } catch (e) {
      setError(e as ApiError)
    } finally {
      setBusy(null)
    }
  }
  const spin = (what: string) => busy === what && <span className="spinner" aria-hidden />

  return (
    <Modal open title={U.manage(user.username)} onClose={onClose}
           actions={<button type="button" className="btn btn-secondary" onClick={onClose}>{t.common.close}</button>}>
      {self && <p className="subtle small"><Icon name="info" size={14} /> {U.selfNote}</p>}
      {error && <ErrorNotice doing={U.failed} error={error} />}

      <div className={styles.manageRow}>
        <label className="field" htmlFor="mu-role">
          <span className="field-label">{U.changeRole}</span>
          <select id="mu-role" className="select" value={user.role} disabled={self || busy !== null}
                  onChange={(e) => run('role', () => api.changeRole(user.id, e.target.value as Role), U.roleChanged(user.username))}>
            {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select>
        </label>
        <button type="button" className={user.is_active ? 'btn btn-danger' : 'btn btn-secondary'} disabled={self || busy !== null}
                onClick={() => run('active', () => api.setUserActive(user.id, !user.is_active),
                  user.is_active ? U.deactivated(user.username) : U.activated(user.username))}>
          {spin('active')} {user.is_active ? U.deactivate : U.activate}
        </button>
      </div>

      <form className={styles.manageRow} onSubmit={(e) => { e.preventDefault(); if (password.length >= 10) run('password', () => api.resetPassword(user.id, password), U.passwordReset(user.username)) }}>
        <label className="field" htmlFor="mu-password">
          <span className="field-label">{U.resetPassword}</span>
          <input id="mu-password" className="input" type="password" autoComplete="new-password" value={password}
                 aria-describedby="mu-password-hint" onChange={(e) => setPassword(e.target.value)} />
          <span id="mu-password-hint" className="field-hint">{U.passwordHint}</span>
        </label>
        <button type="submit" className="btn btn-secondary" disabled={password.length < 10 || busy !== null}>{spin('password')} {U.resetPassword}</button>
      </form>

      <form className={styles.manageRow} onSubmit={(e) => { e.preventDefault(); run('google', () => api.linkGoogle(user.id, email || null), U.googleLinked(user.username)) }}>
        <label className="field" htmlFor="mu-email">
          <span className="field-label">{U.linkGoogle}</span>
          <input id="mu-email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <button type="submit" className="btn btn-secondary" disabled={busy !== null || email === (user.email ?? '')}>
          {spin('google')} {email ? t.common.save : U.unlink}
        </button>
      </form>

      {user.role === 'member' && (
        <form className={styles.manageRow} onSubmit={(e) => { e.preventDefault(); run('member', () => api.linkMember(user.id, memberId ? Number(memberId) : null), U.memberLinked(user.username)) }}>
          <label className="field" htmlFor="mu-member">
            <span className="field-label">{U.linkMember}</span>
            <MemberSelect id="mu-member" value={memberId} onChange={setMemberId}
                          members={members.filter((m) => !m.user_id || m.id === user.member_id)} />
          </label>
          <button type="submit" className="btn btn-secondary" disabled={busy !== null || memberId === (user.member_id ? String(user.member_id) : '')}>
            {spin('member')} {memberId ? t.common.save : U.unlink}
          </button>
        </form>
      )}
    </Modal>
  )
}
