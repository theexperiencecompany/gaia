"use client";

import {
  Button,
  Input,
  Label,
  Modal,
  Radio,
  RadioGroup,
  TextArea,
  TextField,
} from "@heroui/react";
import { useState } from "react";
import { todoApi } from "@/features/todo/api/todoApi";
import { toast } from "@/lib/toast";
import type { ProjectCreate } from "@/types/features/todoTypes";

interface AddProjectModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: () => void;
}

const colorOptions = [
  { value: "#ef4444", label: "Red" },
  { value: "#f97316", label: "Orange" },
  { value: "#eab308", label: "Yellow" },
  { value: "#22c55e", label: "Green" },
  { value: "#3b82f6", label: "Blue" },
  { value: "#8b5cf6", label: "Purple" },
  { value: "#ec4899", label: "Pink" },
  { value: "#6b7280", label: "Gray" },
];

export default function AddProjectModal({
  open,
  onOpenChange,
  onSuccess,
}: AddProjectModalProps) {
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState<ProjectCreate>({
    name: "",
    description: "",
    color: "#3b82f6",
  });

  const handleSubmit = async () => {
    if (!formData.name.trim()) {
      toast.error("Please enter a project name");
      return;
    }

    setLoading(true);
    try {
      await todoApi.createProject(formData);

      // Reset form
      setFormData({
        name: "",
        description: "",
        color: "#3b82f6",
      });

      onOpenChange(false);
      onSuccess?.();
    } catch (error) {
      console.error("Failed to create project:", error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal isOpen={open} onOpenChange={onOpenChange}>
      <Modal.Backdrop>
        <Modal.Container placement="center" size="md">
          <Modal.Dialog>
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Header className="flex flex-col gap-1">
              <Modal.Heading>Create New Project</Modal.Heading>
            </Modal.Header>
            <Modal.Body>
              <div className="flex flex-col gap-4">
                {/* Name */}
                <TextField
                  isRequired
                  value={formData.name}
                  onChange={(name) =>
                    setFormData((prev) => ({ ...prev, name }))
                  }
                >
                  <Label>Project Name</Label>
                  <Input placeholder="Enter project name..." autoFocus />
                </TextField>

                {/* Description */}
                <TextField
                  value={formData.description || ""}
                  onChange={(description) =>
                    setFormData((prev) => ({ ...prev, description }))
                  }
                >
                  <Label>Description</Label>
                  <TextArea placeholder="Add a description..." rows={3} />
                </TextField>

                {/* Color */}
                <div>
                  <label
                    className="mb-2 block text-sm font-medium text-foreground-600"
                    htmlFor="radiogroupcolorpicker"
                  >
                    Project Color
                  </label>
                  <RadioGroup
                    id="radiogroupcolorpicker"
                    value={formData.color}
                    onChange={(value) =>
                      setFormData((prev) => ({ ...prev, color: value }))
                    }
                    orientation="horizontal"
                    className="flex gap-8 p-3"
                  >
                    {colorOptions.map((option) => (
                      <Radio
                        key={option.value}
                        value={option.value}
                        className="p-0"
                      >
                        <Radio.Content>
                          <Radio.Control>
                            <Radio.Indicator />
                          </Radio.Control>
                          <div className="flex h-full w-full items-center">
                            <div
                              className="h-7 w-7 rounded-full"
                              style={{ backgroundColor: option.value }}
                            />
                          </div>
                        </Radio.Content>
                      </Radio>
                    ))}
                  </RadioGroup>
                </div>
              </div>
            </Modal.Body>
            <Modal.Footer>
              <Button variant="tertiary" onPress={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button
                onPress={handleSubmit}
                isPending={loading}
                variant="primary"
              >
                Create Project
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
