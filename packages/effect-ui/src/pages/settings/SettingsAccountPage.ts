import type { View } from "@effect/ui";
import { Command, Component, Query, UiSchema } from "@effect/ui";
import { Html, HtmlFiles } from "@effect/ui/html";
import type { H } from "@effect/ui/html/Html";
import { Effect, Schema } from "effect";
import { AsyncResult } from "effect/reactivity";
import { Api, ApiError } from "../../services/Api";

/**
 * `/settings/account`, ported 1:1 from
 * `apps/web/src/app/[locale]/(main)/settings/[section]/SettingsSectionClient.tsx`
 * and `apps/web/src/features/settings/components/AccountSettings.tsx`, with
 * `ui/SettingsPage`, `ui/SettingsSection` and `ui/SettingsRow` inlined.
 *
 * The route renders the content column only: `SettingsMenu` lives in the
 * sidebar's `UserContainer`, not in this route, so it is not part of the port.
 *
 * Parity notes:
 *
 * - Every class comes from the React tree. `SettingsRow`'s `cn(...)` result is
 *   written out: `tailwind-merge` drops `ml-4` for `ml-0` in the stacked rows.
 * - HeroUI's `Button` and `Input` are rebuilt from the theme's own class
 *   strings (`@heroui/theme` button + input variants) with the same DOM: the
 *   tokens were diffed against `button()` and `input()` resolved output. Only
 *   the selectors HeroUI drives from JavaScript are rewritten:
 *   `data-[hover=true]:` → `hover:`, `group-data-[focus=true]:` →
 *   `focus-within:`, and `group-data-[focus-visible=true]:` →
 *   `has-[:focus-visible]:`.
 * - The `<input type="file" class="hidden">` under the avatar is replaced by
 *   `HtmlFiles.pick` on the avatar button, so there is no ref to click.
 *
 * Not ported (React-only surface): the `toast` calls (loading/success/error)
 * and the `ConfirmActionDialog` behind "Sign out"; `PasswordChangeSection`
 * renders nothing unless the instance runs local auth.
 */

/** The subset of `GET /user/me` this page shows. */
export const CurrentUser = Schema.Struct({
  name: Schema.optionalKey(Schema.NullOr(Schema.String)),
  email: Schema.optionalKey(Schema.NullOr(Schema.String)),
  picture: Schema.optionalKey(Schema.NullOr(Schema.String)),
});

export type CurrentUser = typeof CurrentUser.Type;

/** `useCurrentUser()`'s frozen all-empty record: what the page paints first. */
const NO_USER: CurrentUser = {};

export const SettingsAccountModel = Schema.Struct({
  editingName: Schema.Boolean,
  nameDraft: Schema.String,
  busy: Schema.Boolean,
});

export type SettingsAccountModel = typeof SettingsAccountModel.Type;

export const SettingsAccountMessage = UiSchema.TaggedEnum({
  PressedNameEdit: {},
  UpdatedNameDraft: { value: Schema.String },
  PressedNameSave: {},
  PressedNameCancel: {},
  PressedAvatarPick: {},
  PickedAvatar: { files: Schema.Array(Schema.instanceOf(File)) },
  SucceededSaveName: {},
  FailedSaveName: { message: Schema.String },
  SucceededUploadPicture: {},
  FailedUploadPicture: { message: Schema.String },
});

type SettingsAccountMessage = typeof SettingsAccountMessage.Type;
type SettingsAccountH = H<SettingsAccountMessage>;
type SettingsAccountChildren = View.Children<SettingsAccountMessage, never>;

/** The @icons solid-rounded glyphs the React section renders, by path. */
const CAMERA_ICON_PATHS = [
  "M12.6951 2.74994C13.356 2.74994 13.8658 2.74036 14.3348 2.90424C14.6036 2.99821 14.8565 3.13311 15.0838 3.30463C15.4803 3.60389 15.7553 4.03405 16.1219 4.58392L16.1443 4.6181C16.2415 4.76388 16.3536 4.93152 16.4559 5.07904C16.5111 5.15865 16.6219 5.30625 16.6629 5.36127C16.8475 5.5553 17.0895 5.68532 17.3533 5.73138C17.4448 5.74732 17.5513 5.74994 17.9442 5.74994C18.8732 5.74994 19.4933 5.74264 20.0193 5.89154C21.2722 6.2462 22.2516 7.22562 22.6063 8.47845C22.7552 9.00454 22.7479 9.6246 22.7479 10.5536V14.5644C22.7479 15.9274 22.7479 17.0266 22.6317 17.8915C22.5106 18.7916 22.2511 19.5494 21.6492 20.1513C21.0473 20.7532 20.2896 21.0127 19.3895 21.1337C18.5246 21.25 17.4254 21.25 16.0623 21.2499H7.93341C6.57038 21.25 5.47116 21.25 4.60626 21.1337C3.70619 21.0127 2.9484 20.7532 2.3465 20.1513C1.74464 19.5494 1.48509 18.7916 1.36407 17.8915C1.24783 17.0266 1.24784 15.9274 1.24786 14.5644V10.5536C1.24786 9.62461 1.24055 9.00454 1.38947 8.47845C1.74416 7.22562 2.72353 6.24621 3.97638 5.89154C4.50247 5.74262 5.1225 5.74994 6.05157 5.74994C6.44438 5.74994 6.55096 5.74732 6.6424 5.73138C6.90627 5.68534 7.14817 5.55532 7.33282 5.36127C7.37376 5.30629 7.48462 5.15868 7.53986 5.07904C7.65027 4.91983 7.77162 4.73726 7.87384 4.58392C8.24044 4.03402 8.51542 3.6039 8.91193 3.30463C9.13929 3.13309 9.39208 2.99822 9.66095 2.90424C10.1299 2.74033 10.6397 2.74994 11.3006 2.74994H12.6951ZM11.9979 7.99994C9.23644 7.99994 6.99786 10.2385 6.99786 12.9999C6.99786 15.7614 9.23644 17.9999 11.9979 17.9999C14.7593 17.9999 16.9979 15.7614 16.9979 12.9999C16.9979 10.2385 14.7593 7.99994 11.9979 7.99994ZM11.9979 9.99994C13.6547 9.99994 14.9979 11.3431 14.9979 12.9999C14.9979 14.6568 13.6547 15.9999 11.9979 15.9999C10.341 15.9999 8.99786 14.6568 8.99786 12.9999C8.99786 11.3431 10.341 9.99994 11.9979 9.99994ZM18.9979 8.49994C18.4456 8.49994 17.9979 8.94765 17.9979 9.49994V9.5097C17.9979 10.062 18.4456 10.5097 18.9979 10.5097C19.5501 10.5097 19.9979 10.062 19.9979 9.5097V9.49994C19.9979 8.94765 19.5501 8.49994 18.9979 8.49994Z",
];

const PENCIL_EDIT_ICON_PATHS = [
  "M16.8846 3.08477C17.9976 1.97174 19.8022 1.97174 20.9152 3.08477C22.0283 4.1978 22.0283 6.00237 20.9152 7.1154L20.4556 7.57505L16.425 3.54442L16.8846 3.08477ZM15.3643 4.60508L19.3949 8.63571L13.2659 14.7647C12.6623 15.3684 11.9059 15.7966 11.0778 16.0036L8.18192 16.7276C7.92634 16.7915 7.65597 16.7166 7.46969 16.5303C7.2834 16.344 7.20851 16.0737 7.27241 15.8181L7.99638 12.9222C8.20342 12.0941 8.63164 11.3377 9.23526 10.7341L15.3643 4.60508ZM10.5138 4.25L10.4522 4.25C8.90646 4.24998 7.66026 4.24996 6.66959 4.36706C5.64431 4.48825 4.76696 4.74633 4.02722 5.3534C3.78107 5.55542 3.55536 5.78112 3.35335 6.02728C2.74627 6.76701 2.48819 7.64436 2.367 8.66963C2.2499 9.6603 2.24992 10.9065 2.24994 12.4522V12.4522V13.0709V13.0709C2.24991 14.8438 2.24989 16.2728 2.401 17.3967C2.55788 18.5635 2.8935 19.546 3.67375 20.3262C4.45402 21.1065 5.43644 21.4421 6.60324 21.599C7.72709 21.75 9.15603 21.75 10.9288 21.75H11.5477C13.0934 21.75 14.3396 21.75 15.3303 21.6329C16.3556 21.5117 17.2329 21.2537 17.9727 20.6466C18.2188 20.4446 18.4445 20.2189 18.6465 19.9727C19.2536 19.233 19.5117 18.3557 19.6329 17.3304C19.75 16.3397 19.75 15.0935 19.7499 13.5479V13.5478V13.4861C19.7499 12.9492 19.3147 12.5139 18.7777 12.5139C18.2408 12.5139 17.8055 12.9492 17.8055 13.4861C17.8055 15.108 17.8039 16.239 17.7019 17.1021C17.6024 17.9438 17.4191 18.4033 17.1434 18.7392C17.0222 18.8869 16.8868 19.0223 16.7391 19.1435C16.4032 19.4192 15.9438 19.6024 15.102 19.7019C14.2389 19.804 13.1079 19.8056 11.486 19.8056H10.9999C9.13922 19.8056 7.84149 19.8035 6.86234 19.6718C5.91115 19.544 5.40745 19.3101 5.04868 18.9513C4.68992 18.5925 4.456 18.0888 4.32811 17.1376C4.19646 16.1585 4.19439 14.8607 4.19439 13V12.5139C4.19439 10.892 4.19598 9.76104 4.29801 8.89788C4.3975 8.05618 4.58079 7.59669 4.85644 7.26081C4.97764 7.11312 5.11307 6.97769 5.26076 6.85649C5.59664 6.58084 6.05613 6.39756 6.89784 6.29806C7.761 6.19604 8.89194 6.19445 10.5138 6.19445C11.0508 6.19445 11.4861 5.75917 11.4861 5.22222C11.4861 4.68528 11.0508 4.25 10.5138 4.25Z",
];

const USER_CIRCLE_ICON_PATHS = [
  "M12 3.20455C7.1424 3.20455 3.20455 7.1424 3.20455 12C3.20455 16.8576 7.1424 20.7955 12 20.7955C16.8576 20.7955 20.7955 16.8576 20.7955 12C20.7955 7.1424 16.8576 3.20455 12 3.20455ZM1.25 12C1.25 6.06294 6.06294 1.25 12 1.25C17.9371 1.25 22.75 6.06294 22.75 12C22.75 17.9371 17.9371 22.75 12 22.75C6.06294 22.75 1.25 17.9371 1.25 12Z",
  "M8.5 9.5C8.5 7.567 10.067 6 12 6C13.933 6 15.5 7.567 15.5 9.5C15.5 11.433 13.933 13 12 13C10.067 13 8.5 11.433 8.5 9.5Z",
  "M5.40873 17.6472C6.43247 15.8556 8.3377 14.75 10.4011 14.75H13.5979C15.6613 14.75 17.5666 15.8556 18.5903 17.6472L19.6094 19.5928C17.6634 21.5432 14.9724 22.7499 11.9996 22.7499C9.0267 22.7499 6.33569 21.5431 4.38965 19.5928L5.40873 17.6472Z",
];

const LOGOUT_ICON_PATHS = [
  "M11.6856 3.25027C11.7518 3.76376 11.75 4.41982 11.75 5.19656L11.75 18.863C11.7501 19.614 11.7501 20.2498 11.6856 20.7503C11.6176 21.2766 11.4638 21.7901 11.0469 22.1848C10.925 22.3003 10.79 22.4021 10.6455 22.4876C10.1515 22.7798 9.61553 22.7866 9.09084 22.7073C8.59102 22.6317 7.9783 22.4567 7.25445 22.2499L7.15469 22.2214C6.42537 22.0131 5.82294 21.841 5.34572 21.6497C4.84346 21.4484 4.41446 21.2011 4.06642 20.8079C3.95414 20.681 3.85193 20.5454 3.76076 20.4026C3.47827 19.9601 3.3584 19.4798 3.30275 18.9417C3.24997 18.4311 3.24999 17.8059 3.25002 17.0492V6.95133C3.24999 6.1946 3.24997 5.5694 3.30275 5.05887C3.3584 4.52076 3.47827 4.04049 3.76076 3.59793C3.85192 3.45513 3.95414 3.31952 4.06642 3.19265C4.41446 2.79943 4.84346 2.55219 5.34572 2.35086C5.82295 2.15956 6.42538 1.98749 7.1547 1.77918L7.20119 1.7659C7.94828 1.55248 8.57881 1.37065 9.09084 1.29324C9.61553 1.21396 10.1515 1.22077 10.6455 1.51297C10.79 1.59847 10.925 1.70028 11.0469 1.8157C11.4638 2.21046 11.6176 2.72394 11.6856 3.25027Z",
  "M16.8483 16.7549C16.2988 16.7005 15.8091 17.1019 15.7546 17.6514C15.699 18.2122 15.5908 18.3696 15.5056 18.4541C15.4273 18.5317 15.2875 18.627 14.8483 18.6856C14.3805 18.748 13.7452 18.75 12.7663 18.75H10.7497C10.1974 18.75 9.74971 19.1978 9.74971 19.75C9.74971 20.3023 10.1974 20.75 10.7497 20.75H12.7663C13.6891 20.75 14.4813 20.7521 15.112 20.668C15.7706 20.5802 16.4013 20.3822 16.9138 19.8741C17.4873 19.3054 17.6715 18.5879 17.7448 17.8487C17.7993 17.2991 17.3979 16.8094 16.8483 16.7549ZM10.7497 3.25004C10.1974 3.25004 9.74971 3.69776 9.74971 4.25004C9.74971 4.80233 10.1974 5.25004 10.7497 5.25004H12.7663C13.7452 5.25004 14.3805 5.25213 14.8483 5.3145C15.2875 5.37309 15.4273 5.46837 15.5056 5.54594C15.5908 5.63048 15.699 5.78789 15.7546 6.34868C15.8091 6.89823 16.2988 7.29963 16.8483 7.24516C17.3979 7.19064 17.7993 6.70096 17.7448 6.15141C17.6715 5.41215 17.4873 4.69466 16.9138 4.12602C16.4013 3.61792 15.7706 3.41987 15.112 3.33207C14.4813 3.24801 13.6891 3.25004 12.7663 3.25004H10.7497Z",
  "M19.8428 8.69444C19.3982 8.36731 18.7728 8.46282 18.4453 8.90733C18.1178 9.35202 18.2126 9.97728 18.6573 10.3048C18.722 10.3537 18.913 10.4983 19.0254 10.586C19.1727 10.701 19.3494 10.8445 19.5371 11.0001H14.25C13.6978 11.0001 13.2501 11.4478 13.25 12.0001C13.25 12.5524 13.6977 13.0001 14.25 13.0001H19.5371C19.3494 13.1557 19.1727 13.2992 19.0254 13.4142C18.913 13.5019 18.6429 13.711 18.5782 13.7599C18.2024 14.1001 18.1383 14.6759 18.4453 15.0929C18.7728 15.5374 19.3982 15.6329 19.8428 15.3058C19.9147 15.2514 20.134 15.0855 20.2559 14.9903C20.4986 14.8009 20.8254 14.5385 21.1553 14.2521C21.4802 13.97 21.8311 13.645 22.1084 13.3312C22.2461 13.1753 22.3873 12.998 22.4991 12.8126C22.5943 12.6546 22.75 12.3607 22.75 12.0001C22.75 11.6395 22.5943 11.3456 22.4991 11.1876C22.3873 11.0022 22.2461 10.8249 22.1084 10.669C21.8311 10.3552 21.4802 10.0302 21.1553 9.74815C20.8254 9.46171 20.4986 9.19929 20.2559 9.00987C20.134 8.91474 19.9147 8.74878 19.8428 8.69444Z",
];

export class GetCurrentUser extends Query.Service<GetCurrentUser>()(
  "Settings/GetCurrentUser",
  {
    // `useCurrentUser` never restales: mutations patch the cache instead.
    success: CurrentUser,
    error: ApiError,
    staleTime: "Infinity",
  },
) {
  static readonly layer = this.toLayer(
    Effect.gen(function* () {
      const api = yield* Api;
      return () => api.request("/user/me", { method: "GET" }, CurrentUser);
    }),
  );
}

/**
 * A multipart body built by hand: `Api.request` sends
 * `content-type: application/json` unless the caller replaces it, and a
 * `FormData` needs the browser's own boundary. A Blob keeps the file's bytes
 * without reading them.
 */
const multipartPicture = (picture: File) => {
  const boundary = `----gaia-effect-ui-${Date.now().toString(16)}`;
  const filename = picture.name.replace(/["\r\n]/g, "_");
  const body = new Blob([
    `--${boundary}\r\ncontent-disposition: form-data; name="picture"; filename="${filename}"\r\ncontent-type: ${picture.type || "application/octet-stream"}\r\n\r\n`,
    picture,
    `\r\n--${boundary}--\r\n`,
  ]);
  return { body, contentType: `multipart/form-data; boundary=${boundary}` };
};

export class SaveName extends Command.Service<SaveName>()("Settings/SaveName", {
  args: { name: Schema.String },
  success: SettingsAccountMessage,
  invalidates: () => [GetCurrentUser],
}) {
  static readonly layer = this.toLayer(
    Effect.gen(function* () {
      const api = yield* Api;
      return ({ name }) =>
        api
          .request(
            "/user/name",
            {
              method: "PATCH",
              body: new URLSearchParams({ name }).toString(),
              headers: { "content-type": "application/x-www-form-urlencoded" },
            },
            CurrentUser,
          )
          .pipe(
            Effect.match({
              onSuccess: () => SettingsAccountMessage.SucceededSaveName(),
              onFailure: (error) =>
                SettingsAccountMessage.FailedSaveName({
                  message: error.message,
                }),
            }),
          );
    }),
  );
}

export class UploadPicture extends Command.Service<UploadPicture>()(
  "Settings/UploadPicture",
  {
    args: { picture: Schema.instanceOf(File) },
    success: SettingsAccountMessage,
    invalidates: () => [GetCurrentUser],
  },
) {
  static readonly layer = this.toLayer(
    Effect.gen(function* () {
      const api = yield* Api;
      return ({ picture }) => {
        const { body, contentType } = multipartPicture(picture);
        return api
          .request(
            "/user/me",
            { method: "PATCH", body, headers: { "content-type": contentType } },
            CurrentUser,
          )
          .pipe(
            Effect.match({
              onSuccess: () => SettingsAccountMessage.SucceededUploadPicture(),
              onFailure: (error) =>
                SettingsAccountMessage.FailedUploadPicture({
                  message: error.message,
                }),
            }),
          );
      };
    }),
  );
}

const currentUser = (
  result: AsyncResult.AsyncResult<CurrentUser, ApiError>,
): CurrentUser => AsyncResult.getOrElse(result, () => NO_USER);

const nameOf = (user: CurrentUser) => user.name ?? "";
const emailOf = (user: CurrentUser) => user.email ?? "";
const pictureOf = (user: CurrentUser) => user.picture ?? "";

const BUTTON_BASE =
  "z-0 group relative inline-flex items-center justify-center box-border appearance-none outline-solid outline-transparent select-none whitespace-nowrap font-normal subpixel-antialiased overflow-hidden tap-highlight-transparent transform-gpu data-[pressed=true]:scale-[0.97] cursor-pointer data-[focus-visible=true]:z-10 data-[focus-visible=true]:outline-2 data-[focus-visible=true]:outline-focus data-[focus-visible=true]:outline-offset-2 [&>svg]:max-w-[theme(spacing.8)] transition-transform-colors-opacity motion-reduce:transition-none hover:opacity-hover";
const BUTTON_SM = "px-3 min-w-16 h-8 text-tiny gap-2 rounded-small";
const BUTTON_SOLID_PRIMARY = "bg-primary text-primary-foreground";
const BUTTON_SOLID_DEFAULT = "bg-default text-default-foreground";
const BUTTON_FLAT_DANGER = "bg-danger/20 text-danger-600 dark:text-danger-500";
const BUTTON_DISABLED = "opacity-disabled pointer-events-none";

// HeroUI resolves `labelPlacement` to "outside" for an Input without a label,
// so the wrapper sits in a `mainWrapper` div and the base keeps its own classes.
const INPUT_BASE_CLASS =
  "group flex flex-col data-[hidden=true]:hidden w-full relative justify-end data-[has-label=true]:mt-[calc(var(--heroui-font-size-small)_+_10px)]";
const INPUT_MAIN_WRAPPER_CLASS = "h-full flex flex-col";
const INPUT_CLASS =
  "w-full font-normal bg-transparent !outline-solid placeholder:text-foreground-500 focus-visible:outline-solid outline-transparent data-[has-start-content=true]:ps-1.5 data-[has-end-content=true]:pe-1.5 data-[type=color]:rounded-none file:cursor-pointer file:bg-transparent file:border-0 autofill:bg-transparent bg-clip-text dark:autofill:[-webkit-text-fill-color:hsl(var(--heroui-foreground))] [&::-ms-reveal]:hidden text-small group-data-[has-value=true]:text-default-foreground";
const INPUT_WRAPPER_CLASS =
  "relative w-full inline-flex tap-highlight-transparent flex-row items-center shadow-xs px-3 gap-3 bg-default-100 hover:bg-default-200 focus-within:bg-default-100 h-10 min-h-10 rounded-medium transition-background motion-reduce:transition-none !duration-150 outline-solid outline-transparent has-[:focus-visible]:z-10 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-focus has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-background";
const INPUT_INNER_WRAPPER_CLASS =
  "inline-flex w-full items-center h-full box-border";

const AVATAR_BUTTON_CLASS =
  "relative h-14 w-14 cursor-pointer overflow-hidden rounded-full bg-zinc-800 transition-shadow duration-200 hover:ring-2 hover:ring-primary hover:ring-offset-2 hover:ring-offset-zinc-900";

const NAME_BUTTON_CLASS =
  "group flex w-full items-center justify-between rounded-xl bg-zinc-800 px-3 py-2.5 text-sm text-white transition-colors duration-200 hover:bg-zinc-700";

const icon = (
  h: SettingsAccountH,
  className: string,
  paths: readonly string[],
  decorative = false,
) =>
  h.svg
    .attr("xmlns", "http://www.w3.org/2000/svg")
    .attr("width", "24")
    .attr("height", "24")
    .attr("viewBox", "0 0 24 24")
    .attr("fill", "currentColor")
    .attr("stroke", "none")
    .attr("stroke-width", "0")
    .attr("stroke-linecap", "round")
    .attr("stroke-linejoin", "round")
    // HeroUI clones a Button's startContent with `aria-hidden`.
    .attr("aria-hidden", decorative ? "true" : undefined)
    .class(className)
    .children(paths.map((d) => h.path.key(d).attr("d", d)));

const SettingsPage = (h: SettingsAccountH, children: SettingsAccountChildren) =>
  h.div.class("mx-auto max-w-2xl space-y-6").children(children);

const SettingsSection = (
  h: SettingsAccountH,
  options: {
    readonly title: string;
    readonly children: SettingsAccountChildren;
  },
) =>
  h.section
    .attr("aria-label", options.title)
    .children(
      h.div
        .class("mb-2 flex items-center gap-2")
        .children(
          h.p
            .class("text-sm font-medium text-zinc-300")
            .children(options.title),
        ),
      h.div
        .class(
          "divide-y divide-zinc-800/60 overflow-hidden rounded-2xl bg-zinc-900/60",
        )
        .children(options.children),
    );

const SettingsRow = (
  h: SettingsAccountH,
  options: {
    readonly label: string;
    readonly description?: string;
    readonly stacked?: boolean;
    readonly children?: SettingsAccountChildren;
  },
) =>
  h.div
    .class(
      `flex px-4 py-3.5 ${
        options.stacked === true ? "flex-col" : "items-center justify-between"
      }`,
    )
    .children(
      h.div
        .class("flex min-w-0 flex-1 items-center gap-3")
        .children(
          h.div
            .class("min-w-0 flex-1")
            .children(
              h.p.class("text-sm text-white").children(options.label),
              options.description === undefined
                ? undefined
                : h.p
                    .class("mt-0.5 text-xs text-zinc-500")
                    .children(options.description),
            ),
        ),
      options.children === undefined
        ? undefined
        : h.div
            .class(
              options.stacked === true
                ? "ml-0 mt-2 w-full shrink-0"
                : "ml-4 shrink-0",
            )
            .children(options.children),
    );

const avatar = (h: SettingsAccountH, name: string, picture: string) =>
  picture !== ""
    ? h.img
        .attr("src", picture)
        .attr("alt", name || "Profile")
        .attr("width", "56")
        .attr("height", "56")
        .class("h-full w-full object-cover")
    : h.div
        .class("flex h-full w-full items-center justify-center")
        .children(icon(h, "h-8 w-8 text-zinc-400", USER_CIRCLE_ICON_PATHS));

const nameEditor = (h: SettingsAccountH, model: SettingsAccountModel) =>
  h.div.class("space-y-3").children(
    h.div
      .class(INPUT_BASE_CLASS)
      .attr("data-has-label", "false")
      .attr("data-has-value", model.nameDraft === "" ? "false" : "true")
      .children(
        h.div.class(INPUT_MAIN_WRAPPER_CLASS).children(
          h.div.class(INPUT_WRAPPER_CLASS).children(
            h.div.class(INPUT_INNER_WRAPPER_CLASS).children(
              h.input
                .attr("type", "text")
                .attr("placeholder", "Enter your name")
                .value(model.nameDraft)
                .class(INPUT_CLASS)
                .on("input", ({ value }) =>
                  SettingsAccountMessage.UpdatedNameDraft({ value }),
                ),
            ),
          ),
        ),
      ),
    h.div.class("flex items-center space-x-3").children(
      h.button
        .attr("type", "button")
        .disabled(model.busy)
        .class(
          `${BUTTON_BASE} ${BUTTON_SM} w-full ${BUTTON_SOLID_PRIMARY} ${
            model.busy ? BUTTON_DISABLED : ""
          }`,
        )
        .on("click", SettingsAccountMessage.PressedNameSave())
        .children(model.busy ? "Saving..." : "Save Changes"),
      h.button
        .attr("type", "button")
        .class(`${BUTTON_BASE} ${BUTTON_SM} w-full ${BUTTON_SOLID_DEFAULT}`)
        .on("click", SettingsAccountMessage.PressedNameCancel())
        .children("Cancel"),
    ),
  );

const AccountSection = (
  h: SettingsAccountH,
  model: SettingsAccountModel,
  user: CurrentUser,
) => {
  const name = nameOf(user);

  return SettingsPage(h, [
    SettingsSection(h, {
      title: "Profile",
      children: [
        SettingsRow(h, {
          label: "Photo",
          stacked: true,
          children: [
            h.div.class("group relative w-fit").children(
              h.button
                .attr("type", "button")
                .attr("aria-label", "Change profile photo")
                .disabled(model.busy)
                .class(AVATAR_BUTTON_CLASS)
                .on("click", SettingsAccountMessage.PressedAvatarPick())
                .children(
                  avatar(h, name, pictureOf(user)),
                  h.div
                    .class(
                      "bg-opacity-50 absolute inset-0 flex items-center justify-center bg-black opacity-0 transition-opacity duration-200 group-hover:opacity-100",
                    )
                    .children(icon(h, "h-6 w-6 text-white", CAMERA_ICON_PATHS)),
                ),
            ),
          ],
        }),
        SettingsRow(h, {
          label: "Name",
          stacked: true,
          children: [
            model.editingName
              ? nameEditor(h, model)
              : h.button
                  .attr("type", "button")
                  .class(NAME_BUTTON_CLASS)
                  .on("click", SettingsAccountMessage.PressedNameEdit())
                  .children(
                    h.span(name || "Loading..."),
                    icon(
                      h,
                      "h-4 w-4 text-zinc-400 transition-colors duration-200 group-hover:text-white",
                      PENCIL_EDIT_ICON_PATHS,
                    ),
                  ),
          ],
        }),
        SettingsRow(h, {
          label: "Email",
          children: [
            h.span.class("text-sm text-zinc-400").children(emailOf(user)),
          ],
        }),
      ],
    }),
    SettingsSection(h, {
      title: "Account",
      children: [
        SettingsRow(h, {
          label: "Sign out",
          description: "Sign out of your account on this device",
          children: [
            h.button
              .attr("type", "button")
              .class(`${BUTTON_BASE} ${BUTTON_SM} ${BUTTON_FLAT_DANGER}`)
              .children(
                icon(h, "h-4 w-4", LOGOUT_ICON_PATHS, true),
                "Sign out",
              ),
          ],
        }),
      ],
    }),
  ]);
};

const SettingsAccountDef = Html.component({
  name: "SettingsAccountPage",
  model: SettingsAccountModel,
  message: SettingsAccountMessage,
  queries: {
    user: { query: GetCurrentUser, args: () => ({}) },
  },
});

export const SettingsAccountPageNoDeps = SettingsAccountDef.make({
  init: () => ({ editingName: false, nameDraft: "", busy: false }),

  update: {
    PressedNameEdit: ($) =>
      $.evolve({
        editingName: true,
        nameDraft: nameOf(currentUser($.queries.user)),
      }),
    UpdatedNameDraft: ($, { value }) => $.evolve({ nameDraft: value }),
    PressedNameSave: ($) =>
      $.model.busy
        ? $.model
        : $.evolve({ busy: true }).run(
            SaveName.make({ name: $.model.nameDraft }).pipe(
              Command.afterRefetch("5 seconds"),
            ),
          ),
    PressedNameCancel: ($) =>
      $.evolve({
        editingName: false,
        nameDraft: nameOf(currentUser($.queries.user)),
      }),
    PressedAvatarPick: ($) =>
      $.run(
        HtmlFiles.pick(
          ({ files }) => SettingsAccountMessage.PickedAvatar({ files }),
          { accept: ["image/*"] },
        ),
      ),
    PickedAvatar: ($, { files }) => {
      const picture = files[0];
      return picture === undefined || $.model.busy
        ? $.model
        : $.evolve({ busy: true }).run(
            UploadPicture.make({ picture }).pipe(
              Command.afterRefetch("5 seconds"),
            ),
          );
    },
    SucceededSaveName: ($) => $.evolve({ busy: false, editingName: false }),
    FailedSaveName: ($) => $.evolve({ busy: false }),
    SucceededUploadPicture: ($) => $.evolve({ busy: false }),
    FailedUploadPicture: ($) => $.evolve({ busy: false }),
  },

  view: (h, model) =>
    h.div.class("flex h-full w-full flex-col").children(
      h.div.class("flex-1 overflow-y-auto").children(
        h.div.class("flex w-full justify-center p-6").children(
          h.div.class("w-full").children(
            AsyncResult.match(h.queries.user, {
              // `useCurrentUser()` answers an all-empty record until the fetch
              // lands, so the first paint is the same tree, not a spinner.
              onInitial: () => AccountSection(h, model, NO_USER),
              onFailure: () => AccountSection(h, model, NO_USER),
              onSuccess: ({ value }) => AccountSection(h, model, value),
            }),
          ),
        ),
      ),
    ),
});

export const SettingsAccountPage = SettingsAccountPageNoDeps.pipe(
  Component.provide([
    GetCurrentUser.layer,
    SaveName.layer,
    UploadPicture.layer,
  ]),
);
