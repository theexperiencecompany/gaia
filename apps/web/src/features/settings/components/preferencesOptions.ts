export const responseStyleOptions = [
  { value: "brief", label: "Brief - Keep responses concise and to the point" },
  { value: "detailed", label: "Detailed - Provide comprehensive explanations" },
  { value: "casual", label: "Casual - Use a friendly and informal tone" },
  {
    value: "professional",
    label: "Professional - Maintain a formal and business-like tone",
  },
  { value: "other", label: "Other - Define your own response style" },
] as const;

export const professionOptions = [
  { value: "student", label: "Student" },
  { value: "developer", label: "Software Developer" },
  { value: "designer", label: "Designer" },
  { value: "manager", label: "Manager" },
  { value: "entrepreneur", label: "Entrepreneur" },
  { value: "consultant", label: "Consultant" },
  { value: "researcher", label: "Researcher" },
  { value: "teacher", label: "Teacher" },
  { value: "writer", label: "Writer" },
  { value: "analyst", label: "Analyst" },
  { value: "engineer", label: "Engineer" },
  { value: "marketer", label: "Marketer" },
  { value: "other", label: "Other" },
] as const;
