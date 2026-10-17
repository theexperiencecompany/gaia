/**
 * What `gaia status` and `gaia doctor` call each compose service and API
 * dependency, so a person reads "API" and "PostgreSQL", not "gaia-backend"
 * and "postgres".
 * @module lib/display-names
 */

const SERVICE_NAMES: Record<string, string> = {
  proxy: "Web proxy",
  "gaia-web": "Web app",
  "gaia-backend": "API",
  arq_worker: "Background worker",
  mongo: "MongoDB",
  postgres: "PostgreSQL",
  redis: "Redis",
  rabbitmq: "RabbitMQ",
  chromadb: "ChromaDB",
  "bot-telegram": "Telegram bot",
  "bot-discord": "Discord bot",
  "bot-slack": "Slack bot",
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

/** An API dependency's product name; an unknown one keeps its own. */
export function dependencyName(dependency: string): string {
  return DEPENDENCY_NAMES[dependency] ?? dependency;
}
