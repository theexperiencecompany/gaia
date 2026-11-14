"use client";

import {
  Checkbox,
  ComboBox,
  Input,
  Label,
  ListBox,
  Radio,
  RadioGroup,
  Select,
  Slider,
  Switch,
  TextArea,
  TextField,
} from "@heroui/react";
import { ComboBoxInput } from "@/components/shared/ComboBoxInput";
import {
  inputVariants,
  sliderVariants,
} from "@/components/shared/controlVariants";
import { fieldVariants } from "@/components/shared/fieldVariants";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
import { shapeVariants } from "@/components/shared/shape";

import { ParityCell, ParitySection } from "./ParityCell";

const OPTIONS = ["Engineer", "Designer", "Founder"];

function SelectOptions() {
  return (
    <Select.Popover>
      <ListBox>
        {OPTIONS.map((option) => (
          <GaiaListBoxItem key={option} id={option} textValue={option} />
        ))}
      </ListBox>
    </Select.Popover>
  );
}

/** Text fields, selects, toggles and sliders in v2's combinations, for the parity harness. */
export function ParityFields() {
  return (
    <>
      <ParitySection title="Input / TextArea">
        <ParityCell id="input/inside-label" wide>
          <TextField className={fieldVariants({ labelPlacement: "inside" })}>
            <Label>Email</Label>
            <Input placeholder="you@example.com" />
          </TextField>
        </ParityCell>
        <ParityCell id="input/placeholder" wide>
          <TextField aria-label="Search">
            <Input placeholder="Search" />
          </TextField>
        </ParityCell>
        <ParityCell id="input/placeholder-sm" wide>
          <TextField
            aria-label="Search"
            className={inputVariants({ size: "sm" })}
          >
            <Input placeholder="Search" />
          </TextField>
        </ParityCell>
        <ParityCell id="input/outside-label-sm" wide>
          <TextField className={inputVariants({ size: "sm" })}>
            <Label>Name</Label>
            <Input placeholder="Your name" />
          </TextField>
        </ParityCell>
        <ParityCell id="input/underlined" wide>
          <TextField aria-label="Title">
            <Input
              className={inputVariants({ variant: "underlined" })}
              placeholder="Title"
            />
          </TextField>
        </ParityCell>
        <ParityCell id="input/pill" wide>
          <TextField
            aria-label="Email"
            className={shapeVariants({ shape: "pill" })}
          >
            <Input placeholder="Email" />
          </TextField>
        </ParityCell>
        <ParityCell id="input/disabled" wide>
          <TextField aria-label="Locked" isDisabled>
            <Input placeholder="Locked" />
          </TextField>
        </ParityCell>
        <ParityCell id="textarea/placeholder" wide>
          <TextField aria-label="Notes">
            <TextArea placeholder="Notes" rows={3} />
          </TextField>
        </ParityCell>
        <ParityCell id="textarea/inside-label" wide>
          <TextField className={fieldVariants({ labelPlacement: "inside" })}>
            <Label>Description</Label>
            <TextArea placeholder="Describe it" rows={3} />
          </TextField>
        </ParityCell>
      </ParitySection>
      <ParitySection title="Select / ComboBox">
        <ParityCell id="select/placeholder" wide>
          <Select aria-label="Profession" placeholder="Select your profession">
            <Select.Trigger>
              <GaiaSelectValue />
              <Select.Indicator />
            </Select.Trigger>
            <SelectOptions />
          </Select>
        </ParityCell>
        <ParityCell id="select/placeholder-sm" wide>
          <Select
            aria-label="Mode"
            placeholder="Mode"
            className={inputVariants({ size: "sm" })}
          >
            <Select.Trigger>
              <GaiaSelectValue />
              <Select.Indicator />
            </Select.Trigger>
            <SelectOptions />
          </Select>
        </ParityCell>
        <ParityCell id="select/selected" wide>
          <Select aria-label="Profession" defaultSelectedKey="Designer">
            <Select.Trigger>
              <GaiaSelectValue />
              <Select.Indicator />
            </Select.Trigger>
            <SelectOptions />
          </Select>
        </ParityCell>
        <ParityCell id="combobox/placeholder" wide>
          <ComboBox aria-label="Country" menuTrigger="input">
            <ComboBoxInput placeholder="Country" />
            <ComboBox.Popover>
              <ListBox>
                {OPTIONS.map((option) => (
                  <GaiaListBoxItem
                    key={option}
                    id={option}
                    textValue={option}
                  />
                ))}
              </ListBox>
            </ComboBox.Popover>
          </ComboBox>
        </ParityCell>
      </ParitySection>
      <ParitySection title="Switch / Checkbox / Radio / Slider">
        {(
          [
            ["switch/sm-off", "sm", false, false],
            ["switch/sm-on", "sm", true, false],
            ["switch/md-off", "md", false, false],
            ["switch/md-on", "md", true, false],
            ["switch/sm-disabled", "sm", true, true],
          ] as const
        ).map(([id, size, on, disabled]) => (
          <ParityCell key={id} id={id}>
            <Switch
              size={size}
              aria-label={id}
              defaultSelected={on}
              isDisabled={disabled}
            >
              <Switch.Content>
                <Switch.Control>
                  <Switch.Thumb />
                </Switch.Control>
              </Switch.Content>
            </Switch>
          </ParityCell>
        ))}
        {(
          [
            ["checkbox/off", false, false],
            ["checkbox/on", true, false],
            ["checkbox/pill-on", true, true],
          ] as const
        ).map(([id, on, pill]) => (
          <ParityCell key={id} id={id}>
            <Checkbox
              aria-label={id}
              defaultSelected={on}
              className={pill ? shapeVariants({ shape: "pill" }) : undefined}
            >
              <Checkbox.Content>
                <Checkbox.Control>
                  <Checkbox.Indicator />
                </Checkbox.Control>
                Label
              </Checkbox.Content>
            </Checkbox>
          </ParityCell>
        ))}
        <ParityCell id="radio/group">
          <RadioGroup
            aria-label="Colour"
            defaultValue="a"
            orientation="horizontal"
          >
            {["a", "b"].map((value) => (
              <Radio key={value} value={value}>
                <Radio.Content>
                  <Radio.Control>
                    <Radio.Indicator />
                  </Radio.Control>
                  Option {value}
                </Radio.Content>
              </Radio>
            ))}
          </RadioGroup>
        </ParityCell>
        {(["md", "sm"] as const).map((size) => (
          <ParityCell key={size} id={`slider/${size}`} wide>
            <Slider
              aria-label="Volume"
              defaultValue={40}
              className={sliderVariants({ size })}
            >
              <Slider.Track>
                <Slider.Fill />
                <Slider.Thumb />
              </Slider.Track>
            </Slider>
          </ParityCell>
        ))}
      </ParitySection>
    </>
  );
}
