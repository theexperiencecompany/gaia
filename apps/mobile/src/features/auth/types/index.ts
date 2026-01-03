export interface UserInfo {
  name: string;
  email: string;
  picture?: string;
  user_id?: string;
}

export interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: UserInfo | null;
}
