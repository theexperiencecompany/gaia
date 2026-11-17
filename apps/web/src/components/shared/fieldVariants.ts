import { tv } from "tailwind-variants";

/**
 * Where a form field's label sits, for TextField, Select, ComboBox and TextArea
 * roots. "inside" is v2's default: a 56px field with the label small at its
 * top-left and the value below it, drawn by the gaia-field-inside rules in base.css.
 */
export const fieldVariants = tv({
  variants: {
    labelPlacement: { outside: "", inside: "gaia-field-inside" },
  },
  defaultVariants: { labelPlacement: "outside" },
});
