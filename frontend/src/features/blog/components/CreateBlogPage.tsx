"use client";

import { Autocomplete, AutocompleteItem } from "@heroui/autocomplete";
import { Avatar } from "@heroui/avatar";
import { Button } from "@heroui/button";
import { Card, CardBody, CardHeader } from "@heroui/card";
import { Chip } from "@heroui/chip";
import { Input, Textarea } from "@heroui/input";
import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { type TeamMember, teamApi } from "@/features/team/api/teamApi";
import { CalendarIcon, File01Icon, UserCircle02Icon } from "@/icons";

import { blogApi } from "../api/blogApi";
import { MarkdownPreview } from "./MarkdownPreview";

// Validation schema
const blogSchema = z.object({
  title: z
    .string()
    .min(1, "Title is required")
    .max(200, "Title must be less than 200 characters"),
  slug: z
    .string()
    .min(1, "Slug is required")
    .max(100, "Slug must be less than 100 characters")
    .regex(
      /^[a-z0-9]+(?:-[a-z0-9]+)*$/,
      "Slug must be lowercase, alphanumeric with hyphens only",
    ),
  content: z.string().min(1, "Content is required"),
  category: z.string().min(1, "Category is required"),
  authors: z.array(z.string()).min(1, "At least one author is required"),
  image: z.any().optional(),
  date: z.string().min(1, "Date is required"),
});

type BlogFormData = z.infer<typeof blogSchema>;

export default function CreateBlogPage() {
  const router = useRouter();
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
  const [selectedAuthors, setSelectedAuthors] = useState<TeamMember[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
  } = useForm<BlogFormData>({
    resolver: zodResolver(blogSchema),
    defaultValues: {
      date: new Date().toISOString().split("T")[0],
      authors: [],
      content: `# Welcome to our blog

This is a sample blog post to demonstrate the markdown capabilities.

## Features

- **Bold text** and *italic text*
- Code blocks and \`inline code\`
- Lists and links

### Code Example

\`\`\`javascript
function greet(name) {
  return \`Hello, \${name}!\`;
}
\`\`\`

> This is a blockquote to showcase the styling.

Happy writing! 🚀`,
    },
  });

  const watchTitle = watch("title");
  const watchContent = watch("content");

  // Auto-generate slug from title
  useEffect(() => {
    if (watchTitle) {
      const slug = watchTitle
        .toLowerCase()
        .replace(/[^a-z0-9\s-]/g, "")
        .replace(/\s+/g, "-")
        .replace(/-+/g, "-")
        .trim();
      setValue("slug", slug);
    }
  }, [watchTitle, setValue]);

  // Load team members
  useEffect(() => {
    const loadTeamMembers = async () => {
      try {
        const members = await teamApi.getTeamMembers();
        setTeamMembers(members);
      } catch (error) {
        console.error("Failed to load team members:", error);
        toast.error("Failed to load team members");
      }
    };

    loadTeamMembers();
  }, []);

  // Update form when authors change
  useEffect(() => {
    setValue(
      "authors",
      selectedAuthors.map((author) => author.id),
    );
  }, [selectedAuthors, setValue]);

  // Update form when image file changes
  useEffect(() => {
    setValue("image", selectedFile);
  }, [selectedFile, setValue]);

  const handleAuthorSelect = (authorId: string) => {
    const author = teamMembers.find((member) => member.id === authorId);
    if (
      author &&
      !selectedAuthors.find((selected) => selected.id === authorId)
    ) {
      setSelectedAuthors((prev) => [...prev, author]);
    }
  };

  const removeAuthor = (authorId: string) => {
    setSelectedAuthors((prev) =>
      prev.filter((author) => author.id !== authorId),
    );
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] || null;
    setSelectedFile(file);
  };

  const handleRemoveFile = () => {
    setSelectedFile(null);
    // Reset the file input
    const fileInput = document.getElementById(
      "image-upload",
    ) as HTMLInputElement;
    if (fileInput) {
      fileInput.value = "";
    }
  };

  // Check if bearer token is configured
  const bearerToken = process.env.NEXT_PUBLIC_BLOG_BEARER_TOKEN;

  const onSubmit = async (data: BlogFormData) => {
    setIsSubmitting(true);

    try {
      // Create FormData to handle file upload
      const formData = new FormData();

      // Add all blog data
      formData.append("title", data.title);
      formData.append("slug", data.slug);
      formData.append("content", data.content);
      formData.append("category", data.category);
      formData.append("date", data.date);

      // Add authors as JSON string
      formData.append("authors", JSON.stringify(data.authors));

      // Add image file if selected
      if (selectedFile) {
        formData.append("image", selectedFile);
      }

      await blogApi.createBlogWithFormData(formData, bearerToken!);
      toast.success("Blog post created successfully!");
      router.push("/blog");
    } catch (error) {
      console.error("Failed to create blog post:", error);
      toast.error("Failed to create blog post. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!bearerToken) {
    return (
      <div className="container mx-auto flex min-h-screen max-w-2xl items-center justify-center px-4 py-8">
        <Card className="text-center">
          <CardBody className="py-12">
            <File01Icon className="mx-auto mb-4 h-12 w-12 text-foreground-400" />
            <h1 className="mb-2 text-xl font-bold">
              Blog Management Not Configured
            </h1>
            <p className="mb-4 text-foreground-600">
              The blog management feature requires authentication configuration.
            </p>
            <p className="text-sm text-foreground-500">
              Please set the{" "}
              <code className="rounded bg-zinc-100 px-2 py-1 dark:bg-zinc-800">
                NEXT_PUBLIC_BLOG_BEARER_TOKEN
              </code>{" "}
              environment variable.
            </p>
            <Button
              className="mt-6"
              variant="flat"
              onPress={() => router.back()}
            >
              Go Back
            </Button>
          </CardBody>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto max-w-4xl px-4 py-8">
      <Card className="shadow-lg">
        <CardHeader className="pb-6">
          <div className="flex items-center gap-3">
            <File01Icon className="h-6 w-6 text-primary" />
            <h1 className="text-2xl font-bold">Create New Blog Post</h1>
          </div>
          <p className="mt-2 text-foreground-600">
            Write and publish a new blog post for your audience
          </p>
        </CardHeader>

        <CardBody>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
            {/* Title & Slug */}
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Input
                label="Title"
                placeholder="Enter blog post title"
                isRequired
                isInvalid={!!errors.title}
                errorMessage={errors.title?.message}
                {...register("title")}
              />
              <Input
                label="Slug"
                placeholder="auto-generated-from-title"
                description="URL-friendly version of the title"
                isRequired
                isInvalid={!!errors.slug}
                errorMessage={errors.slug?.message}
                {...register("slug")}
              />
            </div>

            {/* Category & Date */}
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Input
                label="Category"
                placeholder="Enter category (e.g., AI Technology, Product Update)"
                isRequired
                isInvalid={!!errors.category}
                errorMessage={errors.category?.message}
                {...register("category")}
              />
              <Input
                label="Date"
                type="date"
                isRequired
                isInvalid={!!errors.date}
                errorMessage={errors.date?.message}
                startContent={
                  <CalendarIcon className="h-4 w-4 text-foreground-400" />
                }
                {...register("date")}
              />
            </div>

            {/* Authors */}
            <div className="space-y-3">
              <label className="text-sm font-medium text-foreground">
                Authors <span className="text-danger">*</span>
              </label>

              <Autocomplete
                placeholder="Search and select authors"
                startContent={
                  <UserCircle02Icon className="h-4 w-4 text-foreground-400" />
                }
                onSelectionChange={(key) => {
                  if (key) handleAuthorSelect(key as string);
                }}
              >
                {teamMembers
                  .filter(
                    (member) =>
                      !selectedAuthors.find(
                        (selected) => selected.id === member.id,
                      ),
                  )
                  .map((member) => (
                    <AutocompleteItem key={member.id}>
                      <div className="flex items-center gap-2">
                        <Avatar
                          src={member.avatar}
                          name={member.name}
                          size="sm"
                        />
                        <div>
                          <div className="font-medium">{member.name}</div>
                          <div className="text-xs text-foreground-500">
                            {member.role}
                          </div>
                        </div>
                      </div>
                    </AutocompleteItem>
                  ))}
              </Autocomplete>

              {/* Selected Authors */}
              {selectedAuthors.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {selectedAuthors.map((author) => (
                    <Chip
                      key={author.id}
                      onClose={() => removeAuthor(author.id)}
                      avatar={
                        <Avatar
                          src={author.avatar}
                          name={author.name}
                          size="sm"
                        />
                      }
                      variant="flat"
                      color="primary"
                    >
                      {author.name}
                    </Chip>
                  ))}
                </div>
              )}

              {errors.authors && (
                <p className="text-xs text-danger">{errors.authors.message}</p>
              )}
            </div>

            {/* Featured Image Upload */}
            <div className="space-y-3">
              <label className="text-sm font-medium text-foreground">
                Featured Image (Optional)
              </label>

              {selectedFile ? (
                <Card className="p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="flex h-12 w-12 items-center justify-center rounded bg-primary/10">
                        <File01Icon className="h-6 w-6 text-primary" />
                      </div>
                      <div>
                        <p className="font-medium">{selectedFile.name}</p>
                        <p className="text-sm text-foreground-500">
                          {(selectedFile.size / (1024 * 1024)).toFixed(2)} MB
                        </p>
                      </div>
                    </div>
                    <Button
                      variant="flat"
                      color="danger"
                      size="sm"
                      onPress={handleRemoveFile}
                      isDisabled={isSubmitting}
                    >
                      Remove
                    </Button>
                  </div>
                </Card>
              ) : (
                <div className="rounded-lg border-2 border-dashed border-foreground-300 p-8 text-center transition-colors hover:border-primary">
                  <input
                    id="image-upload"
                    type="file"
                    accept="image/*"
                    onChange={handleFileChange}
                    className="hidden"
                    disabled={isSubmitting}
                  />
                  <label
                    htmlFor="image-upload"
                    className="flex cursor-pointer flex-col items-center gap-3"
                  >
                    <div className="flex h-12 w-12 items-center justify-center rounded-full bg-foreground-100">
                      <File01Icon className="h-6 w-6 text-foreground-400" />
                    </div>
                    <div>
                      <p className="font-medium">Click to upload image</p>
                      <p className="text-sm text-foreground-500">
                        PNG, JPG, WebP or GIF up to 10MB
                      </p>
                    </div>
                  </label>
                </div>
              )}

              <p className="text-xs text-foreground-500">
                Upload a banner image for your blog post. Recommended:
                1200×630px for optimal display.
              </p>
              {errors.image && (
                <p className="text-xs text-danger">
                  {typeof errors.image === "object" &&
                  errors.image !== null &&
                  "message" in errors.image
                    ? String(errors.image.message)
                    : "Invalid image file"}
                </p>
              )}
            </div>

            {/* Content with Preview */}
            <div className="space-y-4">
              <label className="text-sm font-medium text-foreground">
                Content <span className="text-danger">*</span>
              </label>

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <div>
                  <Textarea
                    placeholder="Write your blog post content in Markdown..."
                    description="You can use Markdown syntax for formatting"
                    minRows={12}
                    isRequired
                    isInvalid={!!errors.content}
                    errorMessage={errors.content?.message}
                    {...register("content")}
                  />
                </div>

                <div className="hidden lg:block">
                  <MarkdownPreview
                    content={watchContent || ""}
                    title={watchTitle}
                  />
                </div>
              </div>
            </div>

            {/* Submit Button */}
            <div className="flex justify-end gap-3 pt-4">
              <Button
                variant="flat"
                onPress={() => router.back()}
                isDisabled={isSubmitting}
              >
                Cancel
              </Button>
              <Button type="submit" color="primary" isLoading={isSubmitting}>
                {isSubmitting ? "Creating..." : "Create Blog Post"}
              </Button>
            </div>
          </form>
        </CardBody>
      </Card>
    </div>
  );
}
