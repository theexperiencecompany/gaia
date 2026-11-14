import type { PartMap } from "./capture";

export type Side = "v2" | "v3";

/**
 * The parts of each primitive the harness reads, by the id's kind (its first
 * segment) and the HeroUI version that rendered it. A part's name is the same
 * on both sides, so v2's input wrapper meets v3's input: they are the element
 * that draws the field. The first part is the origin the others' offsets are
 * measured from. v2's selectors are what captured v2-snapshot.json.
 */
export const INLINE_PARTS: Record<Side, Record<string, PartMap>> = {
  v2: {
    button: { root: "css::scope > button" },
    buttongroup: { group: "css::scope > *", button: "all:button" },
    input: {
      box: "css:[data-slot=input-wrapper]",
      text: "css:input",
      label: "css:label",
    },
    textarea: {
      box: "css:[data-slot=input-wrapper]",
      text: "css:textarea",
      label: "css:label",
    },
    select: {
      box: "css:[data-slot=trigger]",
      value: "css:[data-slot=value]",
      icon: "css:[data-slot=selectorIcon]",
    },
    combobox: { box: "css:[data-slot=input-wrapper]", text: "css:input" },
    switch: {
      root: "css:label",
      track: "css:label > span",
      thumb: "css:label > span > span",
    },
    checkbox: {
      root: "css:label",
      control: "css:label > span",
      text: "text:Label",
    },
    radio: {
      root: "css::scope > *",
      control: "all:label > span:first-of-type",
      text: "text:Option a",
    },
    slider: {
      track: "css:[data-slot=track]",
      fill: "css:[data-slot=filler]",
      thumb: "css:[data-slot=thumb]",
    },
    chip: { root: "css::scope > *", text: "text:Chip" },
    tabs: {
      list: "css:[data-slot=tabList]",
      tab: "all:[data-slot=tab]",
      text: "all:[data-slot=tabContent]",
      indicator: "css:[data-slot=cursor]",
    },
    accordion: {
      root: "css::scope > *",
      item: "all:[data-slot=base]",
      trigger: "all:[data-slot=trigger]",
      title: "all:[data-slot=title]",
      indicator: "all:[data-slot=indicator]",
      content: "css:[data-slot=content]",
    },
    avatar: { root: "css::scope > *", text: "text:AR" },
    card: {
      root: "css::scope > *",
      header: "text:Title",
      title: "text:Title",
      body: "text:Body text",
    },
    divider: { root: "css::scope > *" },
    skeleton: { root: "css::scope > *" },
    spinner: { root: "css::scope > *" },
    kbd: { root: "css:kbd", abbr: "css:abbr" },
    progress: {
      root: "css::scope > *",
      track: "css:[role=progressbar] > div",
      fill: "css:[role=progressbar] > div > div",
    },
    pagination: {
      root: "css::scope > *",
      // v2 draws the current page as a cursor over its cell: the cursor is "active", the other cells items
      item: "all:[data-slot=item]:not([data-active=true])",
      active: "css:[data-slot=cursor]",
      prev: "css:[data-slot=prev]",
    },
    table: {
      root: "css::scope > * > div",
      column: "all:th",
      cell: "all:td",
    },
  },
  v3: {
    button: { root: "css::scope > button" },
    buttongroup: { group: "css::scope > *", button: "all:.button" },
    input: { box: "css:input", text: "css:input", label: "css:label" },
    textarea: {
      box: "css:textarea",
      text: "css:textarea",
      label: "css:label",
    },
    select: {
      box: "css:.select__trigger",
      value: "css:.select__value",
      icon: "css:.select__indicator",
    },
    combobox: { box: "css:.combo-box__input-group", text: "css:input" },
    switch: {
      root: "css:.switch",
      track: "css:.switch__control",
      thumb: "css:.switch__thumb",
    },
    checkbox: {
      root: "css:.checkbox",
      control: "css:.checkbox__control",
      text: "text:Label",
    },
    radio: {
      root: "css::scope > *",
      control: "all:.radio__control",
      text: "text:Option a",
    },
    slider: {
      track: "css:.slider__track",
      fill: "css:.slider__fill",
      thumb: "css:.slider__thumb",
    },
    chip: { root: "css::scope > *", text: "text:Chip" },
    tabs: {
      list: "css:.tabs__list",
      tab: "all:.tabs__tab",
      text: "all:.tabs__tab",
      indicator: "css:.tabs__indicator",
    },
    accordion: {
      root: "css::scope > *",
      item: "all:.accordion__item",
      trigger: "all:.accordion__trigger",
      title: "all:.accordion__trigger",
      indicator: "all:.accordion__indicator",
      content: "css:.accordion__panel > div",
    },
    avatar: { root: "css::scope > *", text: "text:AR" },
    card: {
      root: "css::scope > *",
      header: "css:.card__header",
      title: "css:.card__title",
      body: "css:.card__content",
    },
    divider: { root: "css::scope > *" },
    skeleton: { root: "css::scope > *" },
    spinner: { root: "css::scope > *" },
    kbd: { root: "css:kbd", abbr: "css:abbr" },
    progress: {
      root: "css::scope > *",
      track: "css:.progress-bar__track",
      fill: "css:.progress-bar__fill",
    },
    pagination: {
      root: "css::scope > *",
      item: "all:.pagination__link:not(.pagination__link--nav, [data-active=true])",
      active: "css:.pagination__link[data-active=true]",
      prev: "css:.pagination__link--nav",
    },
    table: { root: "css::scope > *", column: "all:th", cell: "all:td" },
  },
};

/** Parts of an open overlay, found from the data-parity-mark inside it; the box comes first. */
export const OVERLAY_PARTS: Record<Side, Record<string, PartMap>> = {
  v2: {
    tooltip: { box: "up:[data-slot=content]", text: "self" },
    popover: { box: "up:[data-slot=content]", text: "self" },
    dropdown: {
      box: "up:[data-slot=content]",
      text: "self",
      item: "up:li",
      danger: "up:ul|li:nth-of-type(4)",
      icon: "up:ul|li:nth-child(2) > svg",
    },
    select: {
      box: "up:[data-slot=content]",
      text: "self",
      item: "up:li",
      indicator: "up:li|svg",
    },
    modal: {
      box: "up:section",
      text: "self",
      header: "up:header",
      body: "up:section|header + div",
      footer: "up:section|footer",
      close: "up:section|:scope > button",
    },
  },
  v3: {
    tooltip: { box: "up:.tooltip", text: "self" },
    popover: { box: "up:.popover", text: "self" },
    dropdown: {
      box: "up:.dropdown__popover",
      text: "self",
      item: "up:.menu-item",
      danger: "up:.dropdown__menu|.menu-item:nth-child(4)",
      icon: "up:.dropdown__menu|.menu-item:nth-child(2) > svg",
    },
    select: {
      box: "up:.select__popover",
      text: "self",
      item: "up:.list-box-item",
      indicator: "up:.list-box-item|.list-box-item__indicator svg",
    },
    modal: {
      box: "up:section",
      text: "self",
      header: "up:.modal__header",
      body: "up:section|.modal__body",
      footer: "up:section|.modal__footer",
      close: "up:section|.close-button",
    },
  },
};

/** The overlays the fixture opens one at a time (?overlay=), each read through its marks. */
export const OVERLAYS = [
  "tooltips",
  "tooltip-delay",
  "popover/default",
  "popover/arrow",
  "dropdown/menu",
  "select/open",
  "modal/sm",
  "modal/md",
  "modal/lg",
  "modal/2xl",
];

/** Interaction states read on top of rest: the part they act on and the element focused for focus. */
export const STATE_TARGETS: Record<
  Side,
  Record<string, { hover: string; focus?: string; press?: boolean }>
> = {
  v2: {
    button: {
      hover: "css::scope > button",
      focus: "css::scope > button",
      press: true,
    },
    buttongroup: { hover: "css:button" },
    input: { hover: "css:[data-slot=input-wrapper]", focus: "css:input" },
    textarea: { hover: "css:[data-slot=input-wrapper]", focus: "css:textarea" },
    select: {
      hover: "css:[data-slot=trigger]",
      focus: "css:[data-slot=trigger]",
    },
    combobox: { hover: "css:[data-slot=input-wrapper]", focus: "css:input" },
    switch: { hover: "css:label", focus: "css:input" },
    checkbox: { hover: "css:label", focus: "css:input" },
    tabs: {
      hover: "css:[data-slot=tab]:nth-child(3)",
      focus: "css:[data-slot=tab]",
    },
    accordion: {
      hover: "css:[data-slot=trigger]",
      focus: "css:[data-slot=trigger]",
    },
    pagination: { hover: "css:[data-slot=item]" },
  },
  v3: {
    button: {
      hover: "css::scope > button",
      focus: "css::scope > button",
      press: true,
    },
    buttongroup: { hover: "css:.button" },
    input: { hover: "css:input", focus: "css:input" },
    textarea: { hover: "css:textarea", focus: "css:textarea" },
    select: { hover: "css:.select__trigger", focus: "css:.select__trigger" },
    combobox: { hover: "css:.combo-box__input-group", focus: "css:input" },
    switch: { hover: "css:.switch__content", focus: "css:input" },
    checkbox: { hover: "css:.checkbox__content", focus: "css:input" },
    tabs: { hover: "css:.tabs__tab:nth-child(2)", focus: "css:.tabs__tab" },
    accordion: {
      hover: "css:.accordion__trigger",
      focus: "css:.accordion__trigger",
    },
    pagination: { hover: "css:.pagination__link:not(.pagination__link--nav)" },
  },
};
