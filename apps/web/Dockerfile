FROM node:24-alpine

WORKDIR /app

# Install pnpm globally
RUN npm install -g pnpm

# Copy only the lockfile and manifest for caching
COPY package.json pnpm-lock.yaml ./

# Install dependencies before bind-mounting
RUN pnpm install

# Copy rest of the files (in case you run standalone)
COPY . .

# Expose dev port
EXPOSE 3000

# Default command
CMD ["sh", "-c", "pnpm install && pnpm dev"]