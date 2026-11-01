import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { defaultLocale, isLocale, LOCALE_COOKIE, localeFromAcceptLanguage } from "./config";

// No locale in the URL: the locale comes from a cookie (set by the language switcher),
// then the browser's Accept-Language, then the default.
export default getRequestConfig(async () => {
  const cookieLocale = (await cookies()).get(LOCALE_COOKIE)?.value;
  const locale = isLocale(cookieLocale)
    ? cookieLocale
    : (localeFromAcceptLanguage((await headers()).get("accept-language")) ?? defaultLocale);

  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default,
  };
});
