import Reactotron from "reactotron-react-native";

if (__DEV__) {
  Reactotron.configure({ name: "GAIA Mobile" }).useReactNative().connect();
}
