// Interface icons: lucide-react (ISC — THIRD_PARTY_NOTICES.md), one thin line style for the
// whole app (owner's decision 2026-11-03: a clean, calm look; pixel art only in the office, the
// cow and the logo). Features import from here, never from lucide-react directly, so the set and
// the stroke stay in one place.
import type { LucideIcon, LucideProps } from "lucide-react";
import {
  AlertTriangle as LucideAlertTriangle,
  ArrowDown as LucideArrowDown,
  ArrowLeft as LucideArrowLeft,
  ArrowRight as LucideArrowRight,
  ArrowUp as LucideArrowUp,
  Ban as LucideBan,
  Bot as LucideBot,
  Brain as LucideBrain,
  Building2 as LucideBuilding2,
  CalendarDays as LucideCalendarDays,
  Check as LucideCheck,
  ChevronDown as LucideChevronDown,
  ChevronLeft as LucideChevronLeft,
  ChevronRight as LucideChevronRight,
  Code2 as LucideCode2,
  Copy as LucideCopy,
  ExternalLink as LucideExternalLink,
  File as LucideFile,
  FileDown as LucideFileDown,
  FileText as LucideFileText,
  Folder as LucideFolder,
  GripVertical as LucideGripVertical,
  History as LucideHistory,
  Info as LucideInfo,
  KeyRound as LucideKeyRound,
  Languages as LucideLanguages,
  Link2 as LucideLink2,
  ListChecks as LucideListChecks,
  Loader2 as LucideLoader2,
  LogOut as LucideLogOut,
  Maximize as LucideMaximize,
  Menu as LucideMenu,
  MessageSquare as LucideMessageSquare,
  Mic as LucideMic,
  Minus as LucideMinus,
  Monitor as LucideMonitor,
  Moon as LucideMoon,
  Network as LucideNetwork,
  OctagonAlert as LucideOctagonAlert,
  OctagonX as LucideOctagonX,
  PanelLeftClose as LucidePanelLeftClose,
  PanelLeftOpen as LucidePanelLeftOpen,
  Paperclip as LucidePaperclip,
  Pause as LucidePause,
  Pencil as LucidePencil,
  Pin as LucidePin,
  PinOff as LucidePinOff,
  Play as LucidePlay,
  Plug as LucidePlug,
  Plus as LucidePlus,
  RefreshCw as LucideRefreshCw,
  RotateCcw as LucideRotateCcw,
  Save as LucideSave,
  Search as LucideSearch,
  Send as LucideSend,
  Settings as LucideSettings,
  Settings2 as LucideSettings2,
  ShieldAlert as LucideShieldAlert,
  ShieldCheck as LucideShieldCheck,
  Sparkles as LucideSparkles,
  Square as LucideSquare,
  SquarePen as LucideSquarePen,
  Sun as LucideSun,
  Trash2 as LucideTrash2,
  UserPlus as LucideUserPlus,
  WifiOff as LucideWifiOff,
  X as LucideX,
} from "lucide-react";
import { forwardRef, type ComponentType } from "react";

export type IconProps = Omit<LucideProps, "ref">;
export type IconComponent = ComponentType<IconProps>;

/** One stroke for every icon; decorative unless the caller gives it a label. */
function icon(Lucide: LucideIcon, name: string): IconComponent {
  const Wrapped = forwardRef<SVGSVGElement, IconProps>(function MolokoIcon(props, ref) {
    return <Lucide ref={ref} strokeWidth={1.75} aria-hidden="true" focusable="false" data-icon={name} {...props} />;
  });
  Wrapped.displayName = name;
  return Wrapped;
}

export const AlertTriangle = icon(LucideAlertTriangle, "AlertTriangle");
export const ArrowDown = icon(LucideArrowDown, "ArrowDown");
export const ArrowLeft = icon(LucideArrowLeft, "ArrowLeft");
export const ArrowRight = icon(LucideArrowRight, "ArrowRight");
export const ArrowUp = icon(LucideArrowUp, "ArrowUp");
export const Ban = icon(LucideBan, "Ban");
export const Bot = icon(LucideBot, "Bot");
export const Brain = icon(LucideBrain, "Brain");
export const Building2 = icon(LucideBuilding2, "Building2");
export const CalendarDays = icon(LucideCalendarDays, "CalendarDays");
export const Check = icon(LucideCheck, "Check");
export const ChevronDown = icon(LucideChevronDown, "ChevronDown");
export const ChevronLeft = icon(LucideChevronLeft, "ChevronLeft");
export const ChevronRight = icon(LucideChevronRight, "ChevronRight");
export const Code2 = icon(LucideCode2, "Code2");
export const Copy = icon(LucideCopy, "Copy");
export const ExternalLink = icon(LucideExternalLink, "ExternalLink");
export const File = icon(LucideFile, "File");
export const FileDown = icon(LucideFileDown, "FileDown");
export const FileText = icon(LucideFileText, "FileText");
export const Folder = icon(LucideFolder, "Folder");
export const GripVertical = icon(LucideGripVertical, "GripVertical");
export const History = icon(LucideHistory, "History");
export const Info = icon(LucideInfo, "Info");
export const KeyRound = icon(LucideKeyRound, "KeyRound");
export const Languages = icon(LucideLanguages, "Languages");
export const Link2 = icon(LucideLink2, "Link2");
export const ListChecks = icon(LucideListChecks, "ListChecks");
export const Loader2 = icon(LucideLoader2, "Loader2");
export const LogOut = icon(LucideLogOut, "LogOut");
export const Maximize = icon(LucideMaximize, "Maximize");
export const Menu = icon(LucideMenu, "Menu");
export const MessageSquare = icon(LucideMessageSquare, "MessageSquare");
export const Mic = icon(LucideMic, "Mic");
export const Minus = icon(LucideMinus, "Minus");
export const Monitor = icon(LucideMonitor, "Monitor");
export const Moon = icon(LucideMoon, "Moon");
export const Network = icon(LucideNetwork, "Network");
export const OctagonAlert = icon(LucideOctagonAlert, "OctagonAlert");
export const OctagonX = icon(LucideOctagonX, "OctagonX");
export const PanelLeftClose = icon(LucidePanelLeftClose, "PanelLeftClose");
export const PanelLeftOpen = icon(LucidePanelLeftOpen, "PanelLeftOpen");
export const Paperclip = icon(LucidePaperclip, "Paperclip");
export const Pause = icon(LucidePause, "Pause");
export const Pencil = icon(LucidePencil, "Pencil");
export const Pin = icon(LucidePin, "Pin");
export const PinOff = icon(LucidePinOff, "PinOff");
export const Play = icon(LucidePlay, "Play");
export const Plug = icon(LucidePlug, "Plug");
export const Plus = icon(LucidePlus, "Plus");
export const RefreshCw = icon(LucideRefreshCw, "RefreshCw");
export const RotateCcw = icon(LucideRotateCcw, "RotateCcw");
export const Save = icon(LucideSave, "Save");
export const Search = icon(LucideSearch, "Search");
export const Send = icon(LucideSend, "Send");
export const Settings = icon(LucideSettings, "Settings");
export const Settings2 = icon(LucideSettings2, "Settings2");
export const ShieldAlert = icon(LucideShieldAlert, "ShieldAlert");
export const ShieldCheck = icon(LucideShieldCheck, "ShieldCheck");
export const Sparkles = icon(LucideSparkles, "Sparkles");
export const Square = icon(LucideSquare, "Square");
export const SquarePen = icon(LucideSquarePen, "SquarePen");
export const Sun = icon(LucideSun, "Sun");
export const Trash2 = icon(LucideTrash2, "Trash2");
export const UserPlus = icon(LucideUserPlus, "UserPlus");
export const WifiOff = icon(LucideWifiOff, "WifiOff");
export const X = icon(LucideX, "X");
