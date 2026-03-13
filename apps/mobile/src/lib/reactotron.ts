import Reactotron from "reactotron-react-native";

if (__DEV__) {
  // biome-ignore lint/correctness/useHookAtTopLevel: Reactotron API method name is not a React Hook.
  Reactotron.configure({ name: "GAIA Mobile" }).useReactNative().connect();
}
