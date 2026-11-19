import { useEffect, useState } from "react"
import { api, displayLabelOf, type Pet, type TimelineRow } from "../api"

export default function TimelineView({ pet }: { pet: Pet }) {
  const [rows, setRows] = useState<TimelineRow[]>([])
  const [error, setError] = useState("")

  useEffect(() => {
    api
      .getTimeline(pet.pet_id)
      .then(setRows)
      .catch((err) => setError(String(err)))
  }, [pet.pet_id])

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-xl font-semibold tracking-tight">{pet.name} 的时间线</h1>
        <p className="text-sm text-ink-soft mt-1">
          识别记录与标注沉淀于此；共 {pet.recognition_count} 条识别、{rows.length} 条时间线事件。
        </p>
      </section>
      {error && <p className="text-sm text-red-500">{error}</p>}
      {rows.length === 0 && !error && <p className="text-sm text-ink-soft">还没有事件——去识别页录一段猫叫吧。</p>}
      <ol className="space-y-0">
        {rows.map((row) => (
          <li key={row.timeline_id} className="grid grid-cols-[7rem_1fr] gap-4 py-4 border-b border-line">
            <div className="text-xs text-ink-soft pt-1">{row.created_at.slice(0, 16).replace("T", " ")}</div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{row.title}</span>
                {row.effective_label && (
                  <span className="px-2 h-5 inline-flex items-center rounded-full bg-accent-soft text-accent text-xs">
                    {displayLabelOf(row.effective_label)}
                  </span>
                )}
              </div>
              <p className="mt-1 text-sm text-ink-soft leading-relaxed">{row.content}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}
