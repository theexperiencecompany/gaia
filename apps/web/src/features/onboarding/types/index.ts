export interface Message {
  id: string;
  type: "bot" | "user";
  content: string;
  questionFieldName?: string;
}

export interface Question {
  id: string;
  question: string;
  placeholder: string;
  fieldName: string;
  chipOptions?: { label: string; value: string }[];
  optional?: boolean;
}

export interface ProfessionOption {
  label: string;
  value: string;
}
