export const SECTIONS = [
  "subjective",
  "objective",
  "assessment",
  "plan",
] as const;
export type Section = (typeof SECTIONS)[number];
export type Note = Record<Section, string> & { reviewNotes: string[] };
export type Result = {
  note: Note;
  transcription: string;
  source: "sample" | "live";
};
export const MAX_TEXT = 20_000;
export const MAX_AUDIO = 10 * 1024 * 1024;
export const SAMPLE_TEXT = `Synthetic consultation for demonstration only.
The patient reports three days of a sore throat and a dry cough. They report no shortness of breath. Temperature measured in the consultation is 37.2 degrees Celsius. The clinician documents a likely viral upper respiratory infection. The clinician advises rest and fluids, and asks the patient to seek review if symptoms worsen or do not improve. No medications, allergies, or other examination findings are documented.`;
export const SAMPLE_NOTE: Note = {
  subjective:
    "Three days of sore throat and dry cough. No shortness of breath reported.",
  objective: "Temperature: 37.2°C. Other examination findings not documented.",
  assessment:
    "Clinician's documented impression: likely viral upper respiratory infection.",
  plan: "Clinician advised rest and fluids, and review if symptoms worsen or do not improve.",
  reviewNotes: [
    "Medications and allergies were not documented. Verify against the original source.",
  ],
};
export function isNote(value: unknown): value is Note {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return (
    SECTIONS.every(
      (key) =>
        typeof item[key] === "string" &&
        item[key].length > 0 &&
        item[key].length <= MAX_TEXT,
    ) &&
    Array.isArray(item.reviewNotes) &&
    item.reviewNotes.length <= 20 &&
    item.reviewNotes.every((v) => typeof v === "string" && v.length <= 2000)
  );
}
export function exportNote(result: Result): string {
  return [
    "Gp Notes — reviewed documentation draft",
    result.source === "sample"
      ? "SYNTHETIC SAMPLE — not a patient record"
      : "AI-assisted draft — not independently clinically validated",
    ...SECTIONS.map(
      (key) => `${key[0].toUpperCase()}${key.slice(1)}\n${result.note[key]}`,
    ),
    `Review notes\n${result.note.reviewNotes.join("\n") || "None recorded."}`,
    `Source transcript\n${result.transcription}`,
  ].join("\n\n");
}
