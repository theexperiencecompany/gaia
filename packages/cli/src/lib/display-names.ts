/**
 * What `gaia status` and `gaia doctor` call each compose service and API
 * dependency, so a person reads "server" and "PostgreSQL", not "gaia-backend"
 * and "postgres".
 * @module lib/display-names
 */

const SERVICE_NAMES: Record<string, string> = {
  proxy: "proxy",
  "gaia-web": "web app",
  "gaia-backend": "server",
  arq_worker: "background jobs",
  mongo: "MongoDB",
  postgres: "PostgreSQL",
  redis: "Redis",
  rabbitmq: "RabbitMQ",
  chromadb: "ChromaDB",
  "bot-telegram": "Telegram bot",
  "bot-discord": "Discord bot",
  "bot-slack": "Slack bot",
};

/** What each image runs, by its short name: the gaia image runs the server and the background jobs. */
const IMAGE_NAMES: Record<string, string> = {
  gaia: "server",
  "gaia-web": "web app",
  caddy: "proxy",
  mongo: "MongoDB",
  postgres: "PostgreSQL",
  redis: "Redis",
  rabbitmq: "RabbitMQ",
  chroma: "ChromaDB",
  "gaia-bot-telegram": "Telegram bot",
  "gaia-bot-discord": "Discord bot",
  "gaia-bot-slack": "Slack bot",
};

const DEPENDENCY_NAMES: Record<string, string> = {
  mongodb: "MongoDB",
  postgres: "PostgreSQL",
  redis: "Redis",
  rabbitmq: "RabbitMQ",
  chromadb: "ChromaDB",
};

/** A compose service's plain name; an unknown service keeps its own. */
export function serviceName(service: string): string {
  return SERVICE_NAMES[service] ?? service;
}

/** An image's plain name, from its short name ("gaia-web"); an unknown image keeps its own. */
export function imageName(image: string): string {
  return IMAGE_NAMES[image] ?? image;
}

/** An API dependency's product name; an unknown one keeps its own. */
export function dependencyName(dependency: string): string {
  return DEPENDENCY_NAMES[dependency] ?? dependency;
}
