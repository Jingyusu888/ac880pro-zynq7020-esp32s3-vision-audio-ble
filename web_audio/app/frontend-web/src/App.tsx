import { useEffect, useState } from "react"
import { api, type Pet } from "./api"
import CandidatesView from "./views/Candidates"
import RecognizeView from "./views/Recognize"
import TimelineView from "./views/Timeline"

type View = "recognize" | "timeline" | "candidates"

const VIEWS: { id: View; label: string }[] = [
  { id: "recognize", label: "识别" },
  { id: "timeline", label: "时间线" },
  { id: "candidates", label: "候选池" },
]

export default function App() {
  const [ready, setReady] = useState(false)
  const [authed, setAuthed] = useState(false)
  const [view, setView] = useState<View>("recognize")
  const [pet, setPet] = useState<Pet | null>(null)
  const [modelConnected, setModelConnected] = useState<boolean | null>(null)
  const [modelNotice, setModelNotice] = useState("")

  async function bootstrap() {
    try {
      const pets = await api.getPets()
      setPet(pets[0] ?? null)
      const status = await api.getStatus()
      setModelConnected(status.model_connected)
      setModelNotice(status.cat_voice.debug_notice)
      setAuthed(true)
    } catch {
      setAuthed(false)
    }
    setReady(true)
  }

  useEffect(() => {
    void bootstrap()
  }, [])

  async function handleLogin(username: string, password: string) {
    await api.login(username, password)
    await bootstrap()
  }

  if (!ready) {
    return <div className="min-h-screen grid place-items-center text-sm text-stone-400">连接后端…</div>
  }

  if (!authed) {
    return <LoginView onLogin={handleLogin} />
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-white/80 backdrop-blur sticky top-0 z-10">
        <div className="mx-auto max-w-3xl px-6 h-14 flex items-center gap-8">
          <span className="text-lg font-semibold tracking-tight">
            Pet<span className="text-accent">Link</span>
          </span>
          <nav className="flex gap-1 text-sm">
            {VIEWS.map((item) => (
              <button
                key={item.id}
                onClick={() => setView(item.id)}
                className={`px-3 h-8 rounded-full transition-colors ${
                  view === item.id ? "bg-accent-soft text-accent font-medium" : "text-ink-soft hover:text-ink"
                }`}
              >
                {item.label}
              </button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2 text-xs text-ink-soft">
            <span
              className={`inline-block h-2 w-2 rounded-full ${modelConnected ? "bg-emerald-500" : "bg-red-400"}`}
              aria-hidden
            />
            {pet ? pet.name : "未建宠物"}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-10">
        {view === "recognize" && (
          <RecognizeView
            pet={pet}
            modelNotice={modelNotice}
            onChanged={() => void bootstrap()}
            goTimeline={() => setView("timeline")}
          />
        )}
        {view === "timeline" && pet && <TimelineView pet={pet} />}
        {view === "candidates" && <CandidatesView />}
      </main>

      <footer className="mx-auto max-w-3xl px-6 pb-10 text-xs text-ink-soft leading-relaxed">
        雏形级模型 · source 隔离评测 · 结果仅供行为观察参考，不能替代兽医判断；"无法判断"是置信度拒识，
        <span className="text-ink"> 不等于"没有猫在叫"</span>。
      </footer>
    </div>
  )
}

function LoginView({ onLogin }: { onLogin: (u: string, p: string) => Promise<void> }) {
  const [username, setUsername] = useState("local_owner")
  const [password, setPassword] = useState("123456")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  return (
    <div className="min-h-screen grid place-items-center px-6">
      <div className="w-full max-w-sm">
        <div className="text-2xl font-semibold tracking-tight mb-1">
          Pet<span className="text-accent">Link</span>
        </div>
        <p className="text-sm text-ink-soft mb-8">猫咪情绪识别雏形 · 本地工作台</p>
        <form
          className="space-y-3"
          onSubmit={async (event) => {
            event.preventDefault()
            setBusy(true)
            setError("")
            try {
              await onLogin(username, password)
            } catch (err) {
              setError(String(err))
            }
            setBusy(false)
          }}
        >
          <input
            className="w-full h-10 px-3 rounded-lg border border-line bg-white text-sm focus:outline-none focus:border-accent"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="用户名"
          />
          <input
            className="w-full h-10 px-3 rounded-lg border border-line bg-white text-sm focus:outline-none focus:border-accent"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="密码"
          />
          {error && <p className="text-xs text-red-500">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="w-full h-10 rounded-lg bg-accent text-white text-sm font-medium hover:brightness-95 disabled:opacity-50"
          >
            {busy ? "登录中…" : "进入工作台"}
          </button>
        </form>
      </div>
    </div>
  )
}
