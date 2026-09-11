import { Extension, type Editor, type Range } from "@tiptap/core";
import { PluginKey } from "@tiptap/pm/state";
import { ReactRenderer } from "@tiptap/react";
import Suggestion, {
  type SuggestionKeyDownProps,
  type SuggestionOptions,
  type SuggestionProps,
} from "@tiptap/suggestion";
import tippy, { type Instance as TippyInstance } from "tippy.js";

import { MentionList, type MentionListProps } from "./MentionList";
import {
  MENTION_TRIGGER,
  filterMentionCandidates,
  mentionContent,
  type MentionCandidate,
  type MentionKind,
} from "./mentionModel";

/**
 * Who and what can be mentioned. Kept in the extension's storage — set with
 * `setMentionSources` whenever the lists change (members load, files
 * refresh) — and read on every keystroke, so the editor never has to be
 * rebuilt for them. An empty list disables that trigger entirely.
 */
export interface MentionSuggestionStorage {
  users: MentionCandidate[];
  files: MentionCandidate[];
}

const TEST_ID: Record<MentionKind, string> = {
  user: "mention-suggestions",
  file: "file-suggestions",
};

type Props = SuggestionProps<MentionCandidate, MentionCandidate>;

/** Replace the trigger and query with the picked mention. */
export function insertMention(
  editor: Editor,
  range: Range,
  kind: MentionKind,
  candidate: MentionCandidate,
) {
  editor.chain().focus().insertContentAt(range, mentionContent(kind, candidate)).run();
}

/**
 * The popup for one trigger. `@tiptap/suggestion` owns the hard parts — it
 * reads the query out of the document (so IME composition, paste and a
 * mouse-moved caret all work), hands over the caret rectangle, and tells us
 * when the `@query` range is left — and tippy/popper places the list next to
 * the caret, flipping above it when the screen runs out below. The React list
 * is mounted through the editor's own renderer so it sits inside the app's
 * providers (translations included).
 */
function popupFor(kind: MentionKind) {
  let list: ReactRenderer | null = null;
  let popup: TippyInstance | null = null;
  let items: MentionCandidate[] = [];
  let query = "";
  let activeIndex = 0;
  let command: Props["command"] | null = null;
  // Escape hides the popup, but the plugin stays active until the `@query`
  // range is left. Without this flag the hidden list would keep taking
  // Enter and Tab.
  let dismissed = false;

  const draw = () => {
    const props: MentionListProps = {
      kind,
      testId: TEST_ID[kind],
      candidates: items,
      query,
      activeIndex,
      onPick: (candidate) => command?.(candidate),
      onHover: (index) => {
        activeIndex = index;
        draw();
      },
    };
    list?.updateProps(props);
  };

  const sync = (props: Props) => {
    if (props.query !== query) activeIndex = 0;
    items = props.items;
    query = props.query;
    command = props.command;
    if (popup) {
      if (props.clientRect) {
        popup.setProps({ getReferenceClientRect: props.clientRect as () => DOMRect });
      }
      // Nothing matching: the list goes away and the keys mean what they
      // normally do, instead of an empty box that swallows Enter.
      if (items.length === 0 || dismissed) popup.hide();
      else popup.show();
    }
    draw();
  };

  return {
    onStart: (props: Props) => {
      dismissed = false;
      activeIndex = 0;
      list = new ReactRenderer(MentionList, {
        editor: props.editor,
        props: {
          kind,
          testId: TEST_ID[kind],
          candidates: [],
          query: "",
          activeIndex: 0,
          onPick: () => {},
        } satisfies MentionListProps,
      });
      if (props.clientRect) {
        popup = tippy(document.body, {
          getReferenceClientRect: props.clientRect as () => DOMRect,
          appendTo: () => document.body,
          content: list.element,
          showOnCreate: false,
          interactive: true,
          trigger: "manual",
          placement: "bottom-start",
          animation: false,
          maxWidth: "none",
        });
      }
      sync(props);
    },

    onUpdate: sync,

    onKeyDown: ({ event }: SuggestionKeyDownProps): boolean => {
      if (dismissed || items.length === 0) return false;
      switch (event.key) {
        case "Escape":
          dismissed = true;
          popup?.hide();
          return true;
        case "ArrowDown":
          activeIndex = (activeIndex + 1) % items.length;
          draw();
          return true;
        case "ArrowUp":
          activeIndex = (activeIndex - 1 + items.length) % items.length;
          draw();
          return true;
        case "Home":
          activeIndex = 0;
          draw();
          return true;
        case "End":
          activeIndex = items.length - 1;
          draw();
          return true;
        case "Tab":
          command?.(items[activeIndex]);
          return true;
        case "Enter":
          // A bare "@" then Enter is somebody starting a new line, not
          // choosing the first name in the list. The newline goes through and
          // the plugin exits because the "@" is no longer at the caret.
          if (query.length === 0) return false;
          command?.(items[activeIndex]);
          return true;
        default:
          return false;
      }
    },

    onExit: () => {
      popup?.destroy();
      popup = null;
      list?.destroy();
      list = null;
      items = [];
      command = null;
      dismissed = false;
    },
  };
}

function suggestionFor(
  kind: MentionKind,
  source: () => MentionCandidate[],
): Omit<SuggestionOptions<MentionCandidate, MentionCandidate>, "editor"> {
  return {
    pluginKey: new PluginKey(`mention-${kind}`),
    char: MENTION_TRIGGER[kind],
    allowSpaces: false,
    allow: () => source().length > 0,
    items: ({ query }) => filterMentionCandidates(source(), query),
    command: ({ editor, range, props }) => insertMention(editor, range, kind, props),
    render: () => popupFor(kind),
  };
}

/** "@" offers people, "#" offers files; each is a suggestion plugin. */
export const MentionSuggestion = Extension.create<Record<string, never>, MentionSuggestionStorage>({
  name: "mentionSuggestion",

  addStorage() {
    return { users: [], files: [] };
  },

  addProseMirrorPlugins() {
    return [
      Suggestion({ editor: this.editor, ...suggestionFor("user", () => this.storage.users) }),
      Suggestion({ editor: this.editor, ...suggestionFor("file", () => this.storage.files) }),
    ];
  },
});

/** Replace the lists offered on "@" and "#". */
export function setMentionSources(editor: Editor, sources: Partial<MentionSuggestionStorage>) {
  const storage = editor.storage.mentionSuggestion as MentionSuggestionStorage | undefined;
  if (!storage) return;
  if (sources.users) storage.users = sources.users;
  if (sources.files) storage.files = sources.files;
}

export default MentionSuggestion;
