// Раскладка ваших субагентов (.claude/agents) по отделам офиса — по 2 узких специалиста в отделе.
// Агентов, которых нет в этом списке, офис сам посадит в отдел «Новые агенты».
// Отдел, куда уже посажен агент, можно поменять в приложении — файл агента при этом не меняется.

export interface DefaultGroup {
  id: string;
  name: string;
  motto: string;
  color: string;
  lead_prompt: string;
  agents: string[];
}

export const DEFAULT_GROUPS: DefaultGroup[] = [
  {
    id: "study",
    name: "Учебный центр",
    motto: "SAT и IELTS без воды",
    color: "#3ab7ff",
    lead_prompt:
      "Подготовка к экзаменам: Digital SAT — sat-trainer, IELTS — ielts-trainer. Передавай задачу ученика нужному тренеру целиком, со всеми его данными (баллы, даты, текст эссе, задача). Если тренеру нужен ответ ученика — пусть спросит через ask_boss.",
    agents: ["sat-trainer", "ielts-trainer"],
  },
  {
    id: "lab",
    name: "Лаборатория кода",
    motto: "Ревью и тесты",
    color: "#5fd07e",
    lead_prompt:
      "Проверка кода на диске офиса: ревью — code-reviewer, тесты и баг-репорты — tester. Для полной проверки сначала ревью, потом тесты, и передай тестировщику находки ревьюера.",
    agents: ["code-reviewer", "tester"],
  },
  {
    id: "ideas",
    name: "Штаб идей",
    motto: "Проверяем идеи и следим за возможностями",
    color: "#ffd23f",
    lead_prompt:
      "Оценка идей и рынка — idea-critic, еженедельный дайджест хакатонов, грантов, учёбы и технологий — digest. Если просят дайджест и сохранить его — пусть digest сохранит файл на диск офиса.",
    agents: ["idea-critic", "digest"],
  },
];

export const NEW_AGENTS_GROUP = {
  name: "Новые агенты",
  motto: "Сюда попадают новые файлы из .claude/agents",
  color: "#9b5cff",
  lead_prompt: "Передавай задачу тому агенту, чьё описание подходит лучше всего.",
};
