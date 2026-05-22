import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import { Pressable, View } from "react-native";
import { AppIcon, Tick02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { selectionHaptic } from "@/lib/haptics";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";

export interface RecurrencePickerSheetRef {
  open: (initial: string | null) => void;
  close: () => void;
}

interface RecurrencePickerSheetProps {
  /** Called with an RRULE string when the user taps Done. Pass null to clear. */
  onDone: (rrule: string | null) => void;
}

type RecurrenceMode = "none" | "daily" | "weekly" | "monthly" | "custom";

type WeekdayCode = "MO" | "TU" | "WE" | "TH" | "FR" | "SA" | "SU";

const WEEKDAY_LABELS: { code: WeekdayCode; label: string }[] = [
  { code: "SU", label: "S" },
  { code: "MO", label: "M" },
  { code: "TU", label: "T" },
  { code: "WE", label: "W" },
  { code: "TH", label: "T" },
  { code: "FR", label: "F" },
  { code: "SA", label: "S" },
];

const MONTH_DAYS = Array.from({ length: 31 }, (_, i) => i + 1);

const MONTHLY_NTH_OPTIONS = [
  { value: "1", label: "first" },
  { value: "2", label: "second" },
  { value: "3", label: "third" },
  { value: "4", label: "fourth" },
  { value: "-1", label: "last" },
];

const MONTHLY_DOW_OPTIONS: { value: WeekdayCode; label: string }[] = [
  { value: "MO", label: "Monday" },
  { value: "TU", label: "Tuesday" },
  { value: "WE", label: "Wednesday" },
  { value: "TH", label: "Thursday" },
  { value: "FR", label: "Friday" },
  { value: "SA", label: "Saturday" },
  { value: "SU", label: "Sunday" },
];

interface RecurrenceState {
  mode: RecurrenceMode;
  dailyInterval: number;
  weeklyInterval: number;
  weeklyDays: WeekdayCode[];
  monthlyMode: "day" | "weekday";
  monthlyDay: number;
  monthlyNth: string;
  monthlyDow: WeekdayCode;
  customFreq: "DAILY" | "WEEKLY" | "MONTHLY" | "YEARLY";
  customInterval: number;
  endMode: "never" | "until" | "count";
  endCount: number;
  endUntil: string;
}

const DEFAULT_STATE: RecurrenceState = {
  mode: "none",
  dailyInterval: 1,
  weeklyInterval: 1,
  weeklyDays: ["MO"],
  monthlyMode: "day",
  monthlyDay: 1,
  monthlyNth: "1",
  monthlyDow: "MO",
  customFreq: "DAILY",
  customInterval: 1,
  endMode: "never",
  endCount: 5,
  endUntil: "",
};

function parseRrule(rrule: string | null): RecurrenceState {
  if (!rrule) return { ...DEFAULT_STATE };
  const map = new Map<string, string>();
  for (const part of rrule.split(";")) {
    const [k, v] = part.split("=");
    if (k && v) map.set(k.toUpperCase(), v);
  }
  const freq = map.get("FREQ");
  const interval = Math.max(1, Number.parseInt(map.get("INTERVAL") ?? "1", 10));
  if (freq === "DAILY") {
    return {
      ...DEFAULT_STATE,
      mode: "daily",
      dailyInterval: interval,
    };
  }
  if (freq === "WEEKLY") {
    const days = (map.get("BYDAY") ?? "MO").split(",") as WeekdayCode[];
    return {
      ...DEFAULT_STATE,
      mode: "weekly",
      weeklyInterval: interval,
      weeklyDays: days.length > 0 ? days : ["MO"],
    };
  }
  if (freq === "MONTHLY") {
    if (map.has("BYMONTHDAY")) {
      return {
        ...DEFAULT_STATE,
        mode: "monthly",
        monthlyMode: "day",
        monthlyDay: Math.max(
          1,
          Number.parseInt(map.get("BYMONTHDAY") ?? "1", 10),
        ),
      };
    }
    if (map.has("BYDAY")) {
      const raw = map.get("BYDAY") ?? "1MO";
      const match = raw.match(/^(-?\d+)(MO|TU|WE|TH|FR|SA|SU)$/);
      if (match) {
        return {
          ...DEFAULT_STATE,
          mode: "monthly",
          monthlyMode: "weekday",
          monthlyNth: match[1],
          monthlyDow: match[2] as WeekdayCode,
        };
      }
    }
  }
  return { ...DEFAULT_STATE, mode: "custom" };
}

function buildRrule(state: RecurrenceState): string | null {
  if (state.mode === "none") return null;
  const tail: string[] = [];
  if (state.endMode === "count") tail.push(`COUNT=${state.endCount}`);
  if (state.endMode === "until" && state.endUntil) {
    tail.push(`UNTIL=${state.endUntil}`);
  }

  if (state.mode === "daily") {
    return ["FREQ=DAILY", `INTERVAL=${state.dailyInterval}`, ...tail].join(";");
  }
  if (state.mode === "weekly") {
    const days = state.weeklyDays.length > 0 ? state.weeklyDays : ["MO"];
    return [
      "FREQ=WEEKLY",
      `INTERVAL=${state.weeklyInterval}`,
      `BYDAY=${days.join(",")}`,
      ...tail,
    ].join(";");
  }
  if (state.mode === "monthly") {
    if (state.monthlyMode === "day") {
      return [
        "FREQ=MONTHLY",
        "INTERVAL=1",
        `BYMONTHDAY=${state.monthlyDay}`,
        ...tail,
      ].join(";");
    }
    return [
      "FREQ=MONTHLY",
      "INTERVAL=1",
      `BYDAY=${state.monthlyNth}${state.monthlyDow}`,
      ...tail,
    ].join(";");
  }
  // custom
  return [
    `FREQ=${state.customFreq}`,
    `INTERVAL=${state.customInterval}`,
    ...tail,
  ].join(";");
}

function ChipRow<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <View className="flex-row flex-wrap" style={{ gap: 8 }}>
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <Pressable
            key={opt.value}
            onPress={() => {
              selectionHaptic();
              onChange(opt.value);
            }}
            style={{
              paddingHorizontal: 12,
              paddingVertical: 8,
              borderRadius: 999,
              backgroundColor: active ? "#00bbff" : "rgba(63,63,70,0.4)",
            }}
          >
            <Text
              style={{
                fontSize: 13,
                fontWeight: "600",
                color: active ? "#000" : "#e4e4e7",
              }}
            >
              {opt.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function Stepper({
  value,
  onChange,
  unit,
}: {
  value: number;
  onChange: (v: number) => void;
  unit: string;
}) {
  return (
    <View className="flex-row items-center" style={{ gap: 12 }}>
      <Pressable
        onPress={() => onChange(Math.max(1, value - 1))}
        style={{
          width: 32,
          height: 32,
          borderRadius: 16,
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "rgba(63,63,70,0.5)",
        }}
      >
        <Text style={{ color: "#e4e4e7", fontSize: 18, fontWeight: "600" }}>
          −
        </Text>
      </Pressable>
      <Text
        style={{
          color: "#f4f4f5",
          fontSize: 15,
          fontWeight: "600",
          minWidth: 96,
          textAlign: "center",
        }}
      >
        Every {value} {unit}
        {value === 1 ? "" : "s"}
      </Text>
      <Pressable
        onPress={() => onChange(value + 1)}
        style={{
          width: 32,
          height: 32,
          borderRadius: 16,
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "rgba(63,63,70,0.5)",
        }}
      >
        <Text style={{ color: "#e4e4e7", fontSize: 18, fontWeight: "600" }}>
          +
        </Text>
      </Pressable>
    </View>
  );
}

export const RecurrencePickerSheet = forwardRef<
  RecurrencePickerSheetRef,
  RecurrencePickerSheetProps
>(({ onDone }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [state, setState] = useState<RecurrenceState>(DEFAULT_STATE);

  useImperativeHandle(ref, () => ({
    open: (initial: string | null) => {
      setState(parseRrule(initial));
      setIsOpen(true);
    },
    close: () => setIsOpen(false),
  }));

  const update = useCallback(
    <K extends keyof RecurrenceState>(key: K, value: RecurrenceState[K]) => {
      setState((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const toggleWeekday = useCallback((code: WeekdayCode) => {
    setState((prev) => {
      const has = prev.weeklyDays.includes(code);
      const next = has
        ? prev.weeklyDays.filter((d) => d !== code)
        : [...prev.weeklyDays, code];
      return { ...prev, weeklyDays: next.length > 0 ? next : prev.weeklyDays };
    });
  }, []);

  const handleDone = useCallback(() => {
    onDone(buildRrule(state));
    setIsOpen(false);
  }, [onDone, state]);

  const handleClear = useCallback(() => {
    onDone(null);
    setIsOpen(false);
  }, [onDone]);

  const modeChips = useMemo(
    () => [
      { value: "daily" as const, label: "Daily" },
      { value: "weekly" as const, label: "Weekly" },
      { value: "monthly" as const, label: "Monthly" },
      { value: "custom" as const, label: "Custom" },
    ],
    [],
  );

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["75%", "95%"]}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#18181b" }}
          handleIndicatorStyle={{ backgroundColor: "#3f3f46", width: 40 }}
        >
          <BottomSheetScrollView
            contentContainerStyle={{
              padding: 20,
              gap: 20,
              paddingBottom: 40,
            }}
          >
            {/* Header */}
            <View className="flex-row items-center justify-between">
              <Text
                style={{
                  fontSize: 17,
                  fontWeight: "600",
                  color: "#f4f4f5",
                }}
              >
                Repeat
              </Text>
              <Pressable
                onPress={handleClear}
                style={{
                  paddingHorizontal: 12,
                  paddingVertical: 6,
                }}
              >
                <Text
                  style={{ fontSize: 13, color: "#71717a", fontWeight: "500" }}
                >
                  Don't repeat
                </Text>
              </Pressable>
            </View>

            <ChipRow<RecurrenceMode>
              options={modeChips}
              value={state.mode === "none" ? "daily" : state.mode}
              onChange={(v) => update("mode", v)}
            />

            {state.mode === "daily" || state.mode === "none" ? (
              <View className="rounded-2xl bg-zinc-800/30 p-4 items-center">
                <Stepper
                  value={state.dailyInterval}
                  onChange={(v) => update("dailyInterval", v)}
                  unit="day"
                />
              </View>
            ) : null}

            {state.mode === "weekly" ? (
              <View
                className="rounded-2xl bg-zinc-800/30 p-4"
                style={{ gap: 16 }}
              >
                <View className="items-center">
                  <Stepper
                    value={state.weeklyInterval}
                    onChange={(v) => update("weeklyInterval", v)}
                    unit="week"
                  />
                </View>
                <View className="flex-row justify-between" style={{ gap: 6 }}>
                  {WEEKDAY_LABELS.map(({ code, label }) => {
                    const active = state.weeklyDays.includes(code);
                    return (
                      <Pressable
                        key={code}
                        onPress={() => toggleWeekday(code)}
                        style={{
                          flex: 1,
                          height: 36,
                          borderRadius: 18,
                          alignItems: "center",
                          justifyContent: "center",
                          backgroundColor: active
                            ? "#00bbff"
                            : "rgba(63,63,70,0.5)",
                        }}
                      >
                        <Text
                          style={{
                            fontSize: 13,
                            fontWeight: "600",
                            color: active ? "#000" : "#e4e4e7",
                          }}
                        >
                          {label}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>
            ) : null}

            {state.mode === "monthly" ? (
              <View
                className="rounded-2xl bg-zinc-800/30 p-4"
                style={{ gap: 16 }}
              >
                {/* Mode radio */}
                <View className="flex-row" style={{ gap: 8 }}>
                  {[
                    { v: "day" as const, label: "On day" },
                    { v: "weekday" as const, label: "On the…" },
                  ].map((opt) => {
                    const active = state.monthlyMode === opt.v;
                    return (
                      <Pressable
                        key={opt.v}
                        onPress={() => update("monthlyMode", opt.v)}
                        style={{
                          flex: 1,
                          paddingVertical: 8,
                          borderRadius: 12,
                          alignItems: "center",
                          backgroundColor: active
                            ? "rgba(0,187,255,0.15)"
                            : "rgba(63,63,70,0.4)",
                        }}
                      >
                        <Text
                          style={{
                            fontSize: 13,
                            fontWeight: "600",
                            color: active ? "#00bbff" : "#e4e4e7",
                          }}
                        >
                          {opt.label}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>

                {state.monthlyMode === "day" ? (
                  <View
                    className="flex-row flex-wrap"
                    style={{ gap: 6, justifyContent: "center" }}
                  >
                    {MONTH_DAYS.map((d) => {
                      const active = state.monthlyDay === d;
                      return (
                        <Pressable
                          key={d}
                          onPress={() => update("monthlyDay", d)}
                          style={{
                            width: 34,
                            height: 34,
                            borderRadius: 17,
                            alignItems: "center",
                            justifyContent: "center",
                            backgroundColor: active
                              ? "#00bbff"
                              : "rgba(63,63,70,0.5)",
                          }}
                        >
                          <Text
                            style={{
                              fontSize: 13,
                              fontWeight: "600",
                              color: active ? "#000" : "#e4e4e7",
                            }}
                          >
                            {d}
                          </Text>
                        </Pressable>
                      );
                    })}
                  </View>
                ) : (
                  <View style={{ gap: 12 }}>
                    <Text
                      style={{
                        fontSize: 11,
                        color: "#71717a",
                        textTransform: "uppercase",
                        letterSpacing: 0.6,
                      }}
                    >
                      Which week
                    </Text>
                    <ChipRow
                      options={MONTHLY_NTH_OPTIONS}
                      value={state.monthlyNth}
                      onChange={(v) => update("monthlyNth", v)}
                    />
                    <Text
                      style={{
                        fontSize: 11,
                        color: "#71717a",
                        textTransform: "uppercase",
                        letterSpacing: 0.6,
                      }}
                    >
                      Day of week
                    </Text>
                    <ChipRow<WeekdayCode>
                      options={MONTHLY_DOW_OPTIONS}
                      value={state.monthlyDow}
                      onChange={(v) => update("monthlyDow", v)}
                    />
                  </View>
                )}
              </View>
            ) : null}

            {state.mode === "custom" ? (
              <View
                className="rounded-2xl bg-zinc-800/30 p-4"
                style={{ gap: 16 }}
              >
                <Text
                  style={{
                    fontSize: 11,
                    color: "#71717a",
                    textTransform: "uppercase",
                    letterSpacing: 0.6,
                  }}
                >
                  Frequency
                </Text>
                <ChipRow<RecurrenceState["customFreq"]>
                  options={[
                    { value: "DAILY", label: "Daily" },
                    { value: "WEEKLY", label: "Weekly" },
                    { value: "MONTHLY", label: "Monthly" },
                    { value: "YEARLY", label: "Yearly" },
                  ]}
                  value={state.customFreq}
                  onChange={(v) => update("customFreq", v)}
                />
                <View className="items-center">
                  <Stepper
                    value={state.customInterval}
                    onChange={(v) => update("customInterval", v)}
                    unit={state.customFreq.toLowerCase().replace(/y$/, "")}
                  />
                </View>
              </View>
            ) : null}

            {/* End condition */}
            <View
              className="rounded-2xl bg-zinc-800/30 p-4"
              style={{ gap: 12 }}
            >
              <Text
                style={{
                  fontSize: 11,
                  color: "#71717a",
                  textTransform: "uppercase",
                  letterSpacing: 0.6,
                }}
              >
                Ends
              </Text>
              {[
                { v: "never" as const, label: "Never" },
                { v: "count" as const, label: "After…" },
                { v: "until" as const, label: "On date" },
              ].map((opt) => {
                const active = state.endMode === opt.v;
                return (
                  <Pressable
                    key={opt.v}
                    onPress={() => update("endMode", opt.v)}
                    className="flex-row items-center"
                    style={{ paddingVertical: 6, gap: 12 }}
                  >
                    <View
                      style={{
                        width: 18,
                        height: 18,
                        borderRadius: 9,
                        borderWidth: 2,
                        borderColor: active ? "#00bbff" : "#52525b",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      {active ? (
                        <View
                          style={{
                            width: 8,
                            height: 8,
                            borderRadius: 4,
                            backgroundColor: "#00bbff",
                          }}
                        />
                      ) : null}
                    </View>
                    <Text
                      style={{
                        flex: 1,
                        fontSize: 14,
                        color: "#e4e4e7",
                        fontWeight: active ? "600" : "400",
                      }}
                    >
                      {opt.label}
                    </Text>
                    {opt.v === "count" && active ? (
                      <Stepper
                        value={state.endCount}
                        onChange={(v) => update("endCount", v)}
                        unit="time"
                      />
                    ) : null}
                  </Pressable>
                );
              })}
            </View>

            {/* Footer */}
            <View className="flex-row" style={{ gap: 12, marginTop: 4 }}>
              <Pressable
                onPress={() => setIsOpen(false)}
                style={{
                  flex: 1,
                  height: 44,
                  borderRadius: 16,
                  alignItems: "center",
                  justifyContent: "center",
                  backgroundColor: "rgba(63,63,70,0.5)",
                }}
              >
                <Text
                  style={{ color: "#e4e4e7", fontSize: 15, fontWeight: "600" }}
                >
                  Cancel
                </Text>
              </Pressable>
              <Pressable
                onPress={handleDone}
                style={{
                  flex: 1,
                  height: 44,
                  borderRadius: 16,
                  alignItems: "center",
                  justifyContent: "center",
                  flexDirection: "row",
                  gap: 8,
                  backgroundColor: "#00bbff",
                }}
              >
                <AppIcon icon={Tick02Icon} size={16} color="#000" />
                <Text
                  style={{ color: "#000", fontSize: 15, fontWeight: "600" }}
                >
                  Done
                </Text>
              </Pressable>
            </View>
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

RecurrencePickerSheet.displayName = "RecurrencePickerSheet";
