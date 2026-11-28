import { HtmlFiles } from "@effect/ui/html";
import { HtmlLocator, HtmlScene } from "@effect/ui/html/testing";
import { Locator, Story } from "@effect/ui/testing";
import { assert, it } from "@effect/vitest";
import { Effect } from "effect";
import {
  SaveName,
  SettingsAccountMessage,
  SettingsAccountPageNoDeps,
  UploadPicture,
} from "../src/pages/settings/SettingsAccountPage";

/** `useCurrentUser()`'s record once `GET /user/me` has answered. */
const user = {
  name: "Ada Lovelace",
  email: "ada@gaia.local",
  picture: "",
};

/** `init`'s Model, so `given` replaces it with the same one. */
const initialModel = { editingName: false, nameDraft: "", busy: false };

it.effect("a loaded user's name, email and photo render", () =>
  Effect.gen(function* () {
    const scene = yield* HtmlScene.make(SettingsAccountPageNoDeps, {});
    scene.given(initialModel, {
      user: { ...user, picture: "https://cdn/ada.png" },
    });

    scene.expect(Locator.text(user.name)).toExist();
    scene.expect(Locator.text(user.email)).toExist();
    // The two `SettingsSection` cards the React page draws, by their labels.
    scene.expect(HtmlLocator.role("region", { name: "Profile" })).toExist();
    scene.expect(HtmlLocator.role("region", { name: "Account" })).toExist();
    scene
      .expect(HtmlLocator.role("img", { name: user.name }))
      .toHaveAttribute("src", "https://cdn/ada.png");
  }),
);

it.effect(
  "the empty record paints the React loading state until the user lands",
  () =>
    Effect.gen(function* () {
      const scene = yield* HtmlScene.make(SettingsAccountPageNoDeps, {});
      // The React page reads `useCurrentUser()`, which is an all-empty record
      // until the fetch answers: "Loading..." and an empty email, not a spinner.
      scene.expect(Locator.text("Loading...")).toExist();
      scene.loaded("user", user);
      scene.expect(Locator.text(user.name)).toExist();
    }),
);

it.effect(
  "editing the name and saving issues SaveName, then closes on the refetch",
  () =>
    Effect.gen(function* () {
      const story = yield* Story.make(SettingsAccountPageNoDeps, {});
      story.given(initialModel, { user });

      story.send(SettingsAccountMessage.PressedNameEdit());
      assert.deepStrictEqual(story.model, {
        editingName: true,
        nameDraft: user.name,
        busy: false,
      });

      // React's `editedName` starts at the cached name, and Cancel restores it.
      story.send(SettingsAccountMessage.PressedNameCancel());
      assert.deepStrictEqual(story.model, {
        editingName: false,
        nameDraft: user.name,
        busy: false,
      });

      story.send(SettingsAccountMessage.PressedNameEdit());
      story.send(
        SettingsAccountMessage.UpdatedNameDraft({ value: "Grace Hopper" }),
      );
      story.send(SettingsAccountMessage.PressedNameSave());

      story.expectExact(SaveName);
      assert.deepStrictEqual(story.pending[0]?.command.args, {
        name: "Grace Hopper",
      });
      assert.isTrue(story.model.busy);

      // `Command.afterRefetch` holds the message until `GetCurrentUser` lands.
      story.resolve(SaveName, SettingsAccountMessage.SucceededSaveName());
      assert.isTrue(story.model.busy);

      story.loaded("user", { ...user, name: "Grace Hopper" });
      assert.deepStrictEqual(story.model, {
        editingName: false,
        nameDraft: "Grace Hopper",
        busy: false,
      });
    }),
);

it.effect("an empty name is saved: the React section has no validation", () =>
  Effect.gen(function* () {
    const story = yield* Story.make(SettingsAccountPageNoDeps, {});
    story.given(initialModel, { user });

    story
      .send(SettingsAccountMessage.PressedNameEdit())
      .send(SettingsAccountMessage.UpdatedNameDraft({ value: "" }))
      .send(SettingsAccountMessage.PressedNameSave())
      .expectExact(SaveName);

    assert.deepStrictEqual(story.pending[0]?.command.args, { name: "" });
    story.resolve(
      SaveName,
      SettingsAccountMessage.FailedSaveName({
        message: "Failed to update name",
      }),
    );
    // The run still invalidates `GetCurrentUser`, so its message waits for the
    // refetch, then the editor stays open with the draft, as React's does.
    story.loaded("user", user);
    assert.isFalse(story.model.busy);
    assert.isTrue(story.model.editingName);
    assert.strictEqual(story.model.nameDraft, "");
  }),
);

it.effect(
  "Save shows Saving... and is disabled while the run is in flight",
  () =>
    Effect.gen(function* () {
      const scene = yield* HtmlScene.make(SettingsAccountPageNoDeps, {});
      scene.given(initialModel, { user });

      scene.click(HtmlLocator.role("button", { name: user.name }));
      scene
        .expect(HtmlLocator.placeholder("Enter your name"))
        .toHaveValue(user.name);

      scene.type(HtmlLocator.placeholder("Enter your name"), "Grace Hopper");
      scene.click(HtmlLocator.role("button", { name: "Save Changes" }));
      scene.expectExact(SaveName);
      scene
        .expect(HtmlLocator.role("button", { name: "Saving..." }))
        .toBeDisabled();

      scene.resolve(SaveName, SettingsAccountMessage.SucceededSaveName());
      scene.loaded("user", { ...user, name: "Grace Hopper" });
      scene.expect(Locator.text("Grace Hopper")).toExist();
      scene
        .expect(HtmlLocator.role("button", { name: "Save Changes" }))
        .toBeAbsent();
    }),
);

it.effect(
  "the avatar button opens the picker and uploads the chosen file",
  () =>
    Effect.gen(function* () {
      const file = new File(["png"], "avatar.png", { type: "image/png" });
      // The avatar button carries an explicit accessible name for screen readers.
      const scene = yield* HtmlScene.make(SettingsAccountPageNoDeps, {});
      scene.given(initialModel, {
        user: { name: "", email: user.email, picture: "https://cdn/ada.png" },
      });

      scene
        .click(HtmlLocator.role("button", { name: "Change profile photo" }))
        .expectExact(HtmlFiles.Pick)
        .resolve(HtmlFiles.Pick, { opened: true, files: [file] })
        .expectExact(UploadPicture);

      assert.strictEqual(
        (
          scene.pending[0]?.command.args as
            | { readonly picture?: File }
            | undefined
        )?.picture,
        file,
      );
      // The avatar is disabled while the upload runs, as `isLoading` does.
      scene
        .expect(HtmlLocator.role("button", { name: "Change profile photo" }))
        .toBeDisabled();

      scene.resolve(
        UploadPicture,
        SettingsAccountMessage.SucceededUploadPicture(),
      );
      scene
        .loaded("user", {
          name: "",
          email: user.email,
          picture: "https://cdn/new.png",
        })
        .expect(HtmlLocator.role("img", { name: "Profile" }))
        .toHaveAttribute("src", "https://cdn/new.png");
    }),
);

it.effect(
  "the Account section shows the sign-out row the React page draws",
  () =>
    Effect.gen(function* () {
      const scene = yield* HtmlScene.make(SettingsAccountPageNoDeps, {});
      scene.given(initialModel, { user });

      // The button is painted for parity; its confirm dialog is not ported, so
      // the view gives it no handler to click.
      scene
        .expect(HtmlLocator.role("button", { name: "Sign out" }))
        .toHaveAttributes({ type: "button", disabled: false });
      scene
        .expect(Locator.text("Sign out of your account on this device"))
        .toExist();
    }),
);
