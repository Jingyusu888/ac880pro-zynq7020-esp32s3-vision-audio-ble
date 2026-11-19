/* PetLink 前端 API 客户端：cookie 会话 + 类型化端点 */

export type Pet = {
  pet_id: string
  name: string
  species: string
  recognition_count: number
}

export type ModelStatus = {
  available: boolean
  model_name: string
  model_type: string
  debug_notice: string
  safety_message: string
}

export type PredictResult = {
  recognition_id: string
  predicted_label: string
  display_label: string
  confidence: number
  margin: number
  trigger: boolean
  warning: string
  debug_notice: string
  safety_message: string
}

export type RecognitionRecord = {
  recognition_id: string
  pet_id: string
  prediction_label: string
  display_label: string
  confidence: number
  margin: number
  trigger: number
  warning: string
  user_label: string
  created_at: string
  original_filename: string
}

export type TimelineRow = {
  timeline_id: string
  event_type: string
  title: string
  content: string
  created_at: string
  effective_label: string
  pet_name: string
}

export type Candidate = {
  candidate_id: string
  recognition_id: string
  prediction_label: string
  user_label: string
  standard_label: string
  user_notes: string
  quality_status: string
  review_status: string
  created_at: string
  model_confidence?: number
}

export type VisionFrame = {
  seq: number
  valid: number
  cls: string
  species_zh: string
  score: number
  pose: string
  pose_zh: string
  raw: string
  kpt_cnt: number
  box: number[]
  ms: number
  source: string
  received_at: string
}

export type VisionStatus = {
  udp_listening: boolean
  udp_port: number
  udp_error: string
  udp_rx_count: number
  esp32_port: string
  esp32_connected: boolean
  esp32_tx_count: number
  esp32_error: string
  stream_stale: boolean
  latest: VisionFrame | null
}

export type MultimodalSummary = {
  vision_active: boolean
  vision: VisionFrame | null
  audio: {
    recognition_id: string
    prediction_label: string
    display_label: string
    confidence: number
    created_at: string
  } | null
  summary: string
  safety_message: string
}

export const LABELS = [
  { value: "affiliative_relaxed", label: "亲近 / 放松" },
  { value: "request_seeking", label: "诉求 / 想要东西" },
  { value: "threat_discomfort", label: "抗拒 / 不适" },
  { value: "pain_distress", label: "痛苦倾向" },
] as const

export function displayLabelOf(value: string): string {
  if (!value) return "—"
  const hit = LABELS.find((item) => item.value === value)
  if (hit) return hit.label
  if (value === "unknown") return "无法判断"
  if (value.endsWith("_uncertain")) return "不确定 / 未触发"
  if (value === "positive_or_request") return "正向 / 诉求倾向"
  if (value === "negative_or_distress") return "负向 / 不适倾向"
  return value
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`${response.status}: ${detail.slice(0, 200)}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  async login(username: string, password: string) {
    return request<{ ok: boolean }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    })
  },
  getPets: () => request<Pet[]>("/api/pets"),
  getStatus: () =>
    request<{ model_connected: boolean; cat_voice: ModelStatus; backend: string }>("/api/smart-tools/status"),
  predict(petId: string, file: File) {
    const form = new FormData()
    form.append("pet_id", petId)
    form.append("audio_file", file)
    return request<PredictResult>("/api/smart-tools/cat-voice/predict", { method: "POST", body: form })
  },
  getRecords: () => request<RecognitionRecord[]>("/api/smart-tools/cat-voice/records"),
  annotate(recognitionId: string, userLabel: string, userNotes: string) {
    return request<unknown>(`/api/smart-tools/cat-voice/${recognitionId}/annotate`, {
      method: "POST",
      body: JSON.stringify({ user_label: userLabel, user_notes: userNotes }),
    })
  },
  saveToTimeline(recognitionId: string) {
    return request<{ ok: boolean }>(`/api/smart-tools/cat-voice/${recognitionId}/save-to-timeline`, { method: "POST" })
  },
  addToCandidates(recognitionId: string) {
    return request<{ candidate: Candidate }>(`/api/smart-tools/cat-voice/${recognitionId}/add-to-training-candidates`, {
      method: "POST",
    })
  },
  getCandidates: () => request<Candidate[]>("/api/smart-tools/cat-voice/training-candidates"),
  reviewCandidate(candidateId: string, qualityStatus: string, reviewStatus: string) {
    return request<Candidate>(`/api/smart-tools/cat-voice/training-candidates/${candidateId}/review`, {
      method: "POST",
      body: JSON.stringify({ quality_status: qualityStatus, review_status: reviewStatus }),
    })
  },
  getTimeline: (petId: string) => request<TimelineRow[]>(`/api/pets/${petId}/timeline`),
  getVisionLatest: () => request<VisionStatus>("/api/vision/latest"),
  getMultimodal: () => request<MultimodalSummary>("/api/vision/multimodal"),
}
