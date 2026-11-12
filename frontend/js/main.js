(function () {
  BZ.route("/login", BZ.authView("login"), { public: true });
  BZ.route("/register", BZ.authView("register"), { public: true });
  BZ.route("/", BZ.ideasView);
  BZ.route("/new", BZ.newIdeaView);
  BZ.route("/idea/:id", BZ.workspaceView);
  BZ.render();
})();
