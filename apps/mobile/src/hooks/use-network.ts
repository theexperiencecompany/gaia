import NetInfo, { NetInfoStateType } from "@react-native-community/netinfo";
import { useEffect, useState } from "react";

interface NetworkState {
  isOnline: boolean;
  isConnected: boolean;
  connectionType: NetInfoStateType;
}

export function useNetwork(): NetworkState {
  const [networkState, setNetworkState] = useState<NetworkState>({
    isOnline: true,
    isConnected: true,
    connectionType: NetInfoStateType.unknown,
  });

  useEffect(() => {
    const unsubscribe = NetInfo.addEventListener((state) => {
      setNetworkState({
        isOnline:
          state.isConnected === true && state.isInternetReachable !== false,
        isConnected: state.isConnected === true,
        connectionType: state.type,
      });
    });

    NetInfo.fetch().then((state) => {
      setNetworkState({
        isOnline:
          state.isConnected === true && state.isInternetReachable !== false,
        isConnected: state.isConnected === true,
        connectionType: state.type,
      });
    });

    return () => {
      unsubscribe();
    };
  }, []);

  return networkState;
}
