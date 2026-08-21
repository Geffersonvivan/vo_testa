/** Config do Tailwind do SITE público (build estático — substitui o Play CDN).
 *  Mesma paleta/fonte da antiga config inline do base.html. Build:
 *    npx tailwindcss@3 -i tailwind.src.css -o apps/site/static/site/css/tailwind.css --minify
 */
module.exports = {
  content: [
    "./apps/site/templates/**/*.html",
    "./apps/site/static/site/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        noturno: "#051C2C",
        madeira: "#4F2C1D",
        lampiao: "#D7A048",
        pergaminho: "#EFDBB2",
        musgo: "#2E483E",
      },
      fontFamily: {
        display: ["Neco", "serif"],
        body: ["Neco", "serif"],
      },
    },
  },
  plugins: [],
};
