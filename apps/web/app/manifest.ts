import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "moloko",
    short_name: "moloko",
    description: "moloko — personal AI office",
    start_url: "/chat",
    scope: "/",
    display: "standalone",
    background_color: "#fbf8ef",
    theme_color: "#fbf8ef",
    lang: "ru",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
