"use client";

export function BlogHeader() {
  // Check if bearer token is configured in client-side environment
  // const hasBearerToken =
  //   typeof window !== "undefined" &&
  //   !!process.env.NEXT_PUBLIC_BLOG_BEARER_TOKEN;

  return (
    <div className="relative mb-8 flex items-center justify-between">
      <div className="flex-1">
        <h1 className="text-4xl font-bold tracking-tight">Blog</h1>
      </div>

      {/* Show create button only if bearer token is configured */}
      {/* {hasBearerToken && (
        <Button
          as={Link}
          href="/blog/create"
          color="primary"
          startContent={<PlusIcon className="h-4 w-4" />}
          className="absolute right-0 ml-4 hidden sm:flex"
        >
          Create Post
        </Button>
      )} */}
    </div>
  );
}
