# HeroUI v3 API cheat sheet (verified against `@heroui/react@3.2.7` type defs)

Everything imports from the single package:

```tsx
import { Button, Modal, Select, Tabs, TextField, Label, Input, FieldError, Description } from "@heroui/react";
```

Read the real types when unsure:
`node_modules/.pnpm/@heroui+react@3.2.7*/node_modules/@heroui/react/dist/components/<component>/index.d.ts`

## Core rules

- **No provider.** `HeroUIProvider` is a pass-through now.
- **`color` is gone from Button.** Colour folds into `variant`.
- **`radius` is gone everywhere.** Use Tailwind (`rounded-full`, `rounded-lg`).
- **`classNames={...}` is gone.** Use `className` on the specific subcomponent.
- **`startContent` / `endContent` are gone.** Put icons as children, or use the
  compound Prefix/Suffix slots where they exist.
- **`onClick` → `onPress`** on buttons/links. (RAC)
- **`isLoading` → `isPending`.**
- **Collection items**: v3 uses RAC, so items take **`id`** *and* **`textValue`**
  (when content isn't plain text). Keep React's `key` as well.

## Component shapes

### Button
```tsx
<Button variant="primary" size="md" isPending={saving} onPress={save}>Save</Button>
```
`variant`: `primary | secondary | tertiary | outline | ghost | danger | danger-soft`
`size`: `sm | md | lg`. `isIconOnly` for square icon buttons.

### Chip
```tsx
<Chip variant="secondary" color="default" size="sm"><Chip.Label>tag</Chip.Label></Chip>
```
`variant`: `primary | secondary | tertiary | soft`; `color`: `default | accent | success | warning | danger`.

### Input / TextField
```tsx
<TextField name="email" type="email" isInvalid={bad} isRequired>
  <Label>Email</Label>
  <Input placeholder="you@example.com" />
  <Description>Never shared</Description>
  <FieldError>Invalid email</FieldError>
</TextField>
```
`Input` alone is a bare `<input>`. With prefix/suffix:
```tsx
<TextField><Label>Price</Label>
  <InputGroup><InputGroup.Prefix>$</InputGroup.Prefix><InputGroup.Input /></InputGroup>
</TextField>
```

### Modal
```tsx
<Modal isOpen={open} onOpenChange={setOpen}>
  <Modal.Backdrop>
    <Modal.Container>
      <Modal.Dialog>
        <Modal.Header><Modal.Heading>Title</Modal.Heading></Modal.Header>
        <Modal.Body>…</Modal.Body>
        <Modal.Footer>…</Modal.Footer>
      </Modal.Dialog>
    </Modal.Container>
  </Modal.Backdrop>
</Modal>
```
`Modal.Root` extends RAC `DialogTrigger`, so `isOpen` / `onOpenChange` still work.

### Select
```tsx
<Select selectedKey={k} onSelectionChange={setK}>
  <Label>Pick</Label>
  <Select.Trigger><Select.Value /><Select.Indicator /></Select.Trigger>
  <Select.Popover>
    <ListBox>
      {items.map((i) => <ListBox.Item key={i.id} id={i.id} textValue={i.label}>{i.label}</ListBox.Item>)}
    </ListBox>
  </Select.Popover>
</Select>
```

### Tabs
```tsx
<Tabs selectedKey={tab} onSelectionChange={setTab}>
  <Tabs.List>
    <Tabs.Tab id="a">A</Tabs.Tab>
    <Tabs.Tab id="b">B</Tabs.Tab>
  </Tabs.List>
  <Tabs.Panel id="a">…</Tabs.Panel>
  <Tabs.Panel id="b">…</Tabs.Panel>
</Tabs>
```

### Accordion
```tsx
<Accordion variant="default">
  <Accordion.Item id="x">
    <Accordion.Heading><Accordion.Trigger>Title<Accordion.Indicator /></Accordion.Trigger></Accordion.Heading>
    <Accordion.Panel>…</Accordion.Panel>
  </Accordion.Item>
</Accordion>
```
`variant`: `default | surface`.

### Card
```tsx
<Card>
  <Card.Header><Card.Title>Title</Card.Title><Card.Description>sub</Card.Description></Card.Header>
  <Card.Content>…</Card.Content>
  <Card.Footer>…</Card.Footer>
</Card>
```

### Switch / Checkbox / Radio
```tsx
<Switch isSelected={on} onSelectedChange={setOn}>
  <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>Label</Switch.Content>
</Switch>
```
Same shape for `Checkbox` (Control + Indicator) and `Radio`.

### Tooltip / Popover
```tsx
<Tooltip><Tooltip.Trigger><Button isIconOnly>?</Button></Tooltip.Trigger><Tooltip.Content>Hint</Tooltip.Content></Tooltip>
<Popover><Popover.Trigger>…</Popover.Trigger><Popover.Content>…</Popover.Content></Popover>
```

### Dropdown
```tsx
<Dropdown>
  <Dropdown.Trigger>…</Dropdown.Trigger>
  <Dropdown.Popover>
    <Menu>
      <Menu.Item id="a" textValue="A">A</Menu.Item>
    </Menu>
  </Dropdown.Popover>
</Dropdown>
```

### Table (RAC)
```tsx
<Table>
  <Table.Header><Table.Column id="name" isRowHeader>Name</Table.Column></Table.Header>
  <Table.Body>{rows.map(r => (
    <Table.Row key={r.id} id={r.id}><Table.Cell>{r.name}</Table.Cell></Table.Row>
  ))}</Table.Body>
</Table>
```

### Progress / Pagination / Slider / Avatar
```tsx
<ProgressBar value={40}><ProgressBar.Track><ProgressBar.Fill /></ProgressBar.Track></ProgressBar>
<Avatar><Avatar.Image src={u} /><Avatar.Fallback>AB</Avatar.Fallback></Avatar>
```

### Removed in v3 — replace with plain HTML
`Snippet`, `User`, `Code`, `Image`, `Navbar`, `Spacer`, `Ripple`.

## Rules for this migration

1. **Preserve behaviour first.** Same handlers, same state, same conditional rendering.
2. **Don't redesign.** If v2 had `variant="flat"`, pick the closest v3 variant, not your favourite.
3. **Don't add dependencies.**
4. **Keep `"use client"`** exactly as it was.
5. If a prop has no v3 equivalent and it was purely cosmetic, drop it; if it changed layout, replace with a Tailwind class that matches the old look.
6. When a component is genuinely ambiguous, prefer the smallest structural change that compiles and renders the same thing.
