# LocWarp dev / build / install shortcuts.
# Run `make help` for the list.

.PHONY: help start dev kill install build build-install push push-build merge-bookmarks merge-routes

# Backup JSON to fold into the live store. Each merge target has its own
# default file; override either with FILE= on the command line:
#   make merge-bookmarks FILE=~/Desktop/whatever.json
#   make merge-routes    FILE=~/Desktop/whatever.json

help:
	@awk 'BEGIN {FS = ":.*##"; printf "Usage:\n  make \033[36m<target>\033[0m\n\nTargets:\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

start: ## Run start.sh (sudo dev launcher — iOS 17+ ready)
	./start.sh

dev: start ## Alias for start

kill: ## Kill all running LocWarp processes (app + backend + helper)
	./scripts/kill-all.sh

build: ## Build the DMG via build-installer-mac.sh
	./build-installer-mac.sh

install: ## Install the *existing* build into /Applications
	./scripts/install-mac-local.sh

build-install: ## Rebuild then install into /Applications (most common iteration)
	./scripts/install-mac-local.sh --build

push: ## Push the *existing* build to all testers (TESTERS= or scripts/testers.conf)
	./scripts/push-to-testers.sh

push-build: ## Rebuild then push to all testers
	./scripts/push-to-testers.sh --build

merge-bookmarks: ## Safely merge a bookmarks backup into the live store (default ~/Desktop/locwarp-bookmark.json; DRY_RUN=1, FORCE=1)
	@cd backend && .venv/bin/python merge_backup.py "$(or $(FILE),$(HOME)/Desktop/locwarp-bookmark.json)" \
		$(if $(DRY_RUN),--dry-run,) $(if $(FORCE),--force-restore,)

merge-routes: ## Safely merge a routes backup into the live store (default ~/Desktop/locwarp-route.json; DRY_RUN=1, FORCE=1)
	@cd backend && .venv/bin/python merge_backup.py "$(or $(FILE),$(HOME)/Desktop/locwarp-route.json)" \
		$(if $(DRY_RUN),--dry-run,) $(if $(FORCE),--force-restore,)
