import type { WeatherData } from "../../../chat/types";
import { formatDateUTC } from "../../../utils/dateUtils";
import type { Card, CardBlock, CardField, CardListItem } from "../types";
import { cappedList, joinMeta, sentenceCase } from "./card-parts";

const WEATHER_TITLE = "Weather";
/** The API asks OpenWeatherMap for metric units. */
const TEMPERATURE_UNIT = "°C";
const WIND_UNIT = "m/s";
const PERCENT = "%";
/** The days after today the card lists; the web card shows the same week. */
const MAX_FORECAST_DAYS = 5;
const FORECAST_HEADING = "Forecast";

type ForecastDay = NonNullable<WeatherData["forecast"]>[number];

function temperature(value: number): string {
  return `${Math.round(value)}${TEMPERATURE_UNIT}`;
}

function place(data: WeatherData): string | undefined {
  const city = data.location?.city ?? data.name;
  const country = data.location?.country ?? data.sys?.country;
  if (!city) return undefined;
  return country ? `${city}, ${country}` : city;
}

/** Current conditions, from the full OpenWeatherMap payload or the flat fallback fields. */
function currentFields(data: WeatherData): CardField[] {
  const temp = data.main?.temp ?? data.temperature;
  const condition = data.weather?.[0]?.description ?? data.condition;
  const humidity = data.main?.humidity ?? data.humidity;
  const wind = data.wind?.speed ?? data.wind_speed;
  const fields: CardField[] = [];
  if (temp != null) {
    fields.push({ label: "Now", value: temperature(temp), inline: true });
  }
  if (condition) {
    fields.push({
      label: "Conditions",
      value: sentenceCase(condition),
      inline: true,
    });
  }
  if (data.main) {
    fields.push(
      {
        label: "Feels like",
        value: temperature(data.main.feels_like),
        inline: true,
      },
      {
        label: "High / Low",
        value: `${temperature(data.main.temp_max)} / ${temperature(data.main.temp_min)}`,
        inline: true,
      },
    );
  }
  if (humidity != null) {
    fields.push({
      label: "Humidity",
      value: `${humidity}${PERCENT}`,
      inline: true,
    });
  }
  if (wind != null) {
    fields.push({ label: "Wind", value: `${wind} ${WIND_UNIT}`, inline: true });
  }
  return fields;
}

function forecastItem(day: ForecastDay): CardListItem {
  return {
    title: formatDateUTC(day.date, "weekday"),
    meta: joinMeta([
      `${temperature(day.temp_max)} / ${temperature(day.temp_min)}`,
      sentenceCase(day.weather.description),
    ]),
  };
}

/** The weather where the user asked: conditions now and the days ahead. */
export function buildWeatherCards(data: WeatherData): Card[] {
  const fields = currentFields(data);
  const forecast = data.forecast ?? [];
  if (fields.length === 0 && forecast.length === 0) return [];
  const blocks: CardBlock[] = [];
  if (fields.length > 0) blocks.push({ kind: "fields", fields });
  if (forecast.length > 0) {
    blocks.push(
      { kind: "text", markdown: `**${FORECAST_HEADING}**` },
      cappedList(forecast, MAX_FORECAST_DAYS, forecastItem),
    );
  }
  const where = place(data);
  return [
    {
      title: where ? `${WEATHER_TITLE} in ${where}` : WEATHER_TITLE,
      accent: "brand",
      blocks,
      actions: [],
    },
  ];
}
