import { useEffect, useState } from "react"
import { api, displayLabelOf, type Candidate } from "../api"

export default function CandidatesView() {
  const [rows, setRows] = useState<Candidate[]>([])
  const [error, setError] = useState("")
  const [filter, setFilter] = useState<"all" | "candidate" | "training_ready" | "excluded">("all")

  async function reload() {
    try {
      setRows(await api.getCandidates())
    } catch (err) {
      setError(String(err))
    }
  }

  useEffect(() => {
    void reload()
  }, [])

  async function review(candidateId: string, qualityStatus: string, reviewStatus: string) {
    await api.reviewCandidate(candidateId, qualityStatus, reviewStatus)
    await reload()
  }

  const visible = rows.filter((row) => filter === "all" || row.review_status === filter)

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-xl font-semibold tracking-tight">训练候选池</h1>
        <p className="text-sm text-ink-soft mt-1">
          用户听后标注进入这里；审核为"训练就绪"的样本将进入下一轮训练清单（needs_human_listen 闭环）。
        </p>
        <div className="mt-4 flex gap-1.5 text-xs">
          {(
            [
              ["all", "全部"],
              ["candidate", "待审核"],
              ["training_ready", "训练就绪"],
              ["excluded", "已排除"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              onClick={() => setFilter(value)}
              className={`px-2.5 h-7 rounded-full border transition-colors ${
                filter === value ? "border-accent bg-accent-soft text-accent" : "border-line text-ink-soft hover:text-ink"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </section>

      {error && <p className="text-sm text-red-500">{error}</p>}
      {visible.length === 0 && !error && <p className="text-sm text-ink-soft">此筛选下没有候选样本。</p>}

      <ul className="divide-y divide-line">
        {visible.map((row) => (
          <li key={row.candidate_id} className="py-4 grid grid-cols-[1fr_auto] gap-4 items-start">
            <div>
              <div className="flex items-center gap-2 text-sm">
                <span className="font-medium">{displayLabelOf(row.standard_label || row.user_label)}</span>
                <span className="text-ink-soft text-xs">
                  模型判定 {displayLabelOf(row.prediction_label)}
                  {row.model_confidence ? `（${(row.model_confidence * 100).toFixed(0)}%）` : ""}
                </span>
              </div>
              <div className="text-xs text-ink-soft mt-1">
                {row.quality_status} · {row.review_status} · {row.created_at.slice(0, 16).replace("T", " ")}
                {row.user_notes ? ` · ${row.user_notes}` : ""}
              </div>
            </div>
            <div className="flex gap-2 text-xs">
              <button
                onClick={() => void review(row.candidate_id, "accepted", "training_ready")}
                className="h-8 px-3 rounded-lg border border-line hover:bg-white"
              >
                训练就绪
              </button>
              <button
                onClick={() => void review(row.candidate_id, "needs_review", "candidate")}
                className="h-8 px-3 rounded-lg border border-line hover:bg-white"
              >
                待人工听
              </button>
              <button
                onClick={() => void review(row.candidate_id, "rejected", "excluded")}
                className="h-8 px-3 rounded-lg border border-line hover:bg-white"
              >
                排除
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
