export const Demo = () => (
  <>
    <ButtonGroup variant="flat" color="primary" fullWidth>
      <Button onPress={connect}>Connect</Button>
      <Dropdown>
        <DropdownTrigger>
          <Button isIconOnly>
            <ChevronDown />
          </Button>
        </DropdownTrigger>
        <DropdownMenu>
          <DropdownItem>
            <Button>Menu action</Button>
          </DropdownItem>
        </DropdownMenu>
      </Dropdown>
    </ButtonGroup>

    <ButtonGroup variant="flat" fullWidth>
      <Button color="danger">Disconnect</Button>
      <Tooltip content="Share">
        <Button color="default">Share</Button>
      </Tooltip>
      <Button variant="ghost">Cancel</Button>
    </ButtonGroup>
  </>
);
