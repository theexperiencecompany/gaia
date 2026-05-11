// Weather data types for weather functionality

// weather data structure for weather intent
export type WeatherData = {
  coord: {
    lon: number;
    lat: number;
  };
  weather: Array<{
    id: number;
    main: string;
    description: string;
    icon: string;
  }>;
  base?: string;
  main: {
    temp: number;
    feels_like: number;
    temp_min: number;
    temp_max: number;
    pressure: number;
    humidity: number;
    sea_level?: number;
    grnd_level?: number;
  };
  visibility?: number;
  wind: {
    speed: number;
    deg: number;
    gust?: number;
  };
  clouds?: {
    all: number;
  };
  dt: number;
  sys: {
    country: string;
    sunrise: number;
    sunset: number;
  };
  timezone: number;
  id?: number;
  name: string;
  cod?: number;
  location: {
    city: string;
    country: string | null;
    region: string | null;
  };
  // New field for forecast data
  forecast?: Array<{
    date: string;
    timestamp: number;
    temp_min: number;
    temp_max: number;
    humidity: number;
    weather: {
      main: string;
      description: string;
      icon: string;
    };
  }>;
};
