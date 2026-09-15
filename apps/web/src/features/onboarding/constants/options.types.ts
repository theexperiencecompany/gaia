import type { NeedOption } from "../types";
import type {
  needOptions,
  OTHER_NEED,
  professionOptions,
  roleNeedOptions,
} from "./options";

export type ProfessionValue = (typeof professionOptions)[number]["value"];

/** Every value a Q2 chip can carry: the shared six, every role pair, and the catch-all. */
export type NeedValue =
  | (typeof needOptions)[number]["value"]
  | (typeof roleNeedOptions)[keyof typeof roleNeedOptions][number]["value"]
  | typeof OTHER_NEED;

/** Every value an onboarding chip can carry. */
export type OptionValue = ProfessionValue | NeedValue;

/** A Q2 option whose value is known at compile time. */
export interface TypedNeedOption extends NeedOption {
  value: NeedValue;
}
