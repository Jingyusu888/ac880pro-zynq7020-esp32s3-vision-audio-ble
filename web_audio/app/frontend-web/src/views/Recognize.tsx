import { useEffect, useRef, useState } from "react"
import { api, LABELS, displayLabelOf, type MultimodalSummary, type Pet, type PredictResult, type VisionStatus } from "../api"

type Props = {
  pet: Pet | null
  modelNotice: string
  onChanged: () => void
  goTimeline: () => void
}

export default function RecognizeView({ pet, modelNotice, onChanged, goTimeline }: Props) {
  const [result, setResult] = useState<PredictResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [annotated, setAnnotated] = useState(false)
  const [saved, setSaved] = useState(false)
  const [candidate, setCandidate] = useState(false)
  const [userLabel, setUserLabel] = useState("")
  const [recording, setRecording] = useState(false)
  const [vision, setVision] = useState<VisionStatus | null>(null)
  const [multimodal, setMultimodal] = useState<MultimodalSummary | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  useEffect(() => {
    let active = true
    async function poll() {
      try {
        const [v, m] = await Promise.all([api.getVisionLatest(), api.getMultimodal()])
        if (active) {
          setVision(v)
          setMultimodal(m)
        }
      } catch {
        // Ignore polling errors when backend restarts
      }
    }
    void poll()
    const id = window.setInterval(() => void poll(), 1500)
    return () => {
      active = false
      window.clearInterval(id)
    }
  }, [result])

  async function handleFile(file: File) {
    if (!pet) {
      setError("尚未建立宠物档案")
      return
    }
    setBusy(true)
    setError("")
    setResult(null)
    setAnnotated(false)
    setSaved(false)
    setCandidate(false)
    setUserLabel("")
    try {
      const outcome = await api.predict(pet.pet_id, file)
      setResult(outcome)
    } catch (err) {
      setError(String(err))
    }
    setBusy(false)
  }

  function toggleRecording() {
    if (recording) {
      recorderRef.current?.stop()
      setRecording(false)
      return
    }
    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then((stream) => {
        const recorder = new MediaRecorder(stream)
        chunksRef.current = []
        recorder.ondataavailable = (event) => chunksRef.current.push(event.data)
        recorder.onstop = () => {
          stream.getTracks().forEach((track) => track.stop())
          const blob = new Blob(chunksRef.current, { type: "audio/webm" })
          handleFile(new File([blob], "recording.webm", { type: "audio/webm" }))
        }
        recorderRef.current = recorder
        recorder.start()
        setRecording(true)
      })
      .catch(() => setError("无法访问麦克风"))
  }

  const labelTone = result?.trigger
    ? result.predicted_label === "pain_distress" || result.predicted_label === "threat_discomfort"
      ? "text-red-600"
      : "text-accent"
    : "text-ink-soft"

  return (
    <div className="space-y-10">
      <section className="rounded-xl border border-line bg-white/70 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold">AC880 实时视觉姿态 · ESP32-S3 联调通道</h2>
            <p className="text-xs text-ink-soft mt-0.5">
              {multimodal?.summary || "等待 AC880 UDP:9000 视觉推流…"}
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className={`px-2 py-1 rounded-full border ${vision?.udp_listening ? "border-accent/40 text-accent bg-accent-soft" : "border-line text-ink-soft"}`}>
              UDP:{vision?.udp_port ?? 9000} {vision?.udp_listening ? `已收 ${vision.udp_rx_count} 帧` : "未监听"}
            </span>
            <span className={`px-2 py-1 rounded-full border ${vision?.esp32_connected ? "border-accent/40 text-accent bg-accent-soft" : "border-line text-ink-soft"}`}>
              ESP32 {vision?.esp32_port || "未绑定"} {vision?.esp32_connected ? `已发 ${vision.esp32_tx_count}` : "离线"}
            </span>
          </div>
        </div>
        {vision?.latest && (
          <div className="mt-3 pt-3 border-t border-line/60 flex flex-wrap items-baseline gap-4 text-sm">
            <span className="font-semibold text-accent">
              {vision.latest.valid ? `${vision.latest.species_zh} · ${vision.latest.pose_zh}` : "画面暂无目标"}
            </span>
            <span className="text-xs text-ink-soft">
              置信度 {(vision.latest.score * 100).toFixed(0)}% · 关键点 {vision.latest.kpt_cnt}/17 · 帧耗时 {vision.latest.ms.toFixed(0)} ms · seq #{vision.latest.seq}
            </span>
          </div>
        )}
      </section>

      <section>
        <h1 className="text-xl font-semibold tracking-tight">识别一段猫叫</h1>
        <p className="text-sm text-ink-soft mt-1">
          上传或录制 1–10 秒音频，模型给出四类情绪倾向与置信度；不确定时拒识。
        </p>
        <div className="mt-5 flex items-center gap-3">
          <label className="inline-flex items-center h-10 px-4 rounded-lg bg-accent text-white text-sm font-medium cursor-pointer hover:brightness-95">
            选择音频文件
            <input
              type="file"
              accept="audio/*"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void handleFile(file)
              }}
            />
          </label>
          <button
            onClick={toggleRecording}
            className={`inline-flex items-center h-10 px-4 rounded-lg text-sm font-medium border ${
              recording ? "border-red-300 text-red-600 bg-red-50 animate-pulse" : "border-line text-ink hover:bg-white"
            }`}
          >
            {recording ? "停止录音" : "录制 4 秒"}
          </button>
          {busy && <span className="text-sm text-ink-soft">分析中…</span>}
        </div>
        {error && <p className="mt-3 text-sm text-red-500">{error}</p>}
      </section>

      {result && (
        <section className="border-t border-line pt-8">
          <div className="flex items-baseline gap-4">
            <span className={`text-4xl font-semibold tracking-tight ${labelTone}`}>
              {result.display_label || displayLabelOf(result.predicted_label)}
            </span>
            <span className="text-sm text-ink-soft">
              置信度 {(result.confidence * 100).toFixed(1)}% · margin {(result.margin * 100).toFixed(1)}%
            </span>
          </div>
          <div className="mt-2 h-1.5 w-56 rounded-full bg-line overflow-hidden">
            <div className="h-full bg-accent" style={{ width: `${Math.round(result.confidence * 100)}%` }} />
          </div>
          <p className="mt-3 text-sm text-ink-soft">{result.safety_message || result.warning}</p>

          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            <div>
              <label className="text-xs font-medium text-ink-soft">听后标注（进入训练闭环）</label>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {LABELS.map((item) => (
                  <button
                    key={item.value}
                    onClick={() => setUserLabel(item.value)}
                    className={`px-2.5 h-8 rounded-full text-xs border transition-colors ${
                      userLabel === item.value ? "border-accent bg-accent-soft text-accent" : "border-line text-ink-soft hover:text-ink"
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-sm">
                <button
                  disabled={!userLabel || annotated}
                  onClick={async () => {
                    if (!result || !userLabel) return
                    await api.annotate(result.recognition_id, userLabel, "web 标注")
                    setAnnotated(true)
                  }}
                  className="h-9 px-3 rounded-lg border border-line hover:bg-white disabled:opacity-40"
                >
                  {annotated ? "已标注 ✓" : "保存标注"}
                </button>
                <button
                  disabled={!userLabel || !annotated || candidate}
                  onClick={async () => {
                    if (!result) return
                    await api.addToCandidates(result.recognition_id)
                    setCandidate(true)
                    onChanged()
                  }}
                  className="h-9 px-3 rounded-lg border border-line hover:bg-white disabled:opacity-40"
                >
                  {candidate ? "已入候选池 ✓" : "加入候选池"}
                </button>
                <button
                  disabled={saved}
                  onClick={async () => {
                    if (!result) return
                    await api.saveToTimeline(result.recognition_id)
                    setSaved(true)
                    onChanged()
                  }}
                  className="h-9 px-3 rounded-lg border border-line hover:bg-white disabled:opacity-40"
                >
                  {saved ? "已存时间线 ✓" : "存入时间线"}
                </button>
                <button onClick={goTimeline} className="h-9 px-3 rounded-lg text-accent hover:bg-accent-soft">
                  查看时间线 →
                </button>
              </div>
            </div>
            <div className="text-xs text-ink-soft leading-relaxed self-end">
              {modelNotice}
              <br />
              未触发 = 置信度拒识（unknown / uncertain），不代表"没有猫在叫"。
            </div>
          </div>
        </section>
      )}
    </div>
  )
}
