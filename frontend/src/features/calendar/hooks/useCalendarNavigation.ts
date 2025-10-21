import { useCallback, useState } from "react";

export const useCalendarNavigation = (initialDate: Date = new Date()) => {
  const [selectedDate, setSelectedDate] = useState(initialDate);
  const [currentWeek, setCurrentWeek] = useState(initialDate);

  const goToPreviousDay = useCallback(() => {
    setSelectedDate((prev) => {
      const newDate = new Date(prev);
      newDate.setDate(prev.getDate() - 1);
      setCurrentWeek(newDate);
      return newDate;
    });
  }, []);

  const goToNextDay = useCallback(() => {
    setSelectedDate((prev) => {
      const newDate = new Date(prev);
      newDate.setDate(prev.getDate() + 1);
      setCurrentWeek(newDate);
      return newDate;
    });
  }, []);

  const goToToday = useCallback(() => {
    const today = new Date();
    setCurrentWeek(today);
    setSelectedDate(today);
  }, []);

  const handleDateChange = useCallback((date: Date) => {
    setSelectedDate(date);
    setCurrentWeek(date);
  }, []);

  return {
    selectedDate,
    currentWeek,
    setSelectedDate,
    setCurrentWeek,
    goToPreviousDay,
    goToNextDay,
    goToToday,
    handleDateChange,
  };
};
