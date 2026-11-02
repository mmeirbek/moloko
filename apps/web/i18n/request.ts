import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import { defaultLocale, isLocale, isTimeZone, LOCALE_COOKIE, localeFromAcceptLanguage, TIMEZONE_COOKIE } from "./config";

// No locale in the URL: the locale comes from a cookie (set by the language switcher),
// then the browser's Accept-Language, then the default.
export default getRequestConfig(async () => {
  const jar = await cookies();
  const cookieLocale = jar.get(LOCALE_COOKIE)?.value;
  const cookieTimeZone = jar.get(TIMEZONE_COOKIE)?.value;
  const locale = isLocale(cookieLocale)
    ? cookieLocale
    : (localeFromAcceptLanguage((await headers()).get("accept-language")) ?? defaultLocale);

  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default,
    // Dates in the owner's time zone (from the browser), not the server's (UTC in Docker).
    timeZone: isTimeZone(cookieTimeZone) ? cookieTimeZone : "UTC",
  };
});
