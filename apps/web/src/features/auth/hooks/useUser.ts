import { useUserStore } from "@/stores/userStore";

export const useUser = () => useUserStore();

export const useUserActions = () => {
  const { setUser, updateUser, clearUser } = useUserStore();

  return {
    setUser,
    updateUser,
    clearUser,
  };
};
