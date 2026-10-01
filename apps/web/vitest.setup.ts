// HeroUI's LazyMotion users (ripple, tooltip, modal, toast, …) import this bundle
// on first render; loaded up front, its setState can no longer land after a test
// file's jsdom teardown ("window is not defined").
import "@heroui/dom-animation";
