# LocWarp dev / build / install shortcuts.
# Run `make help` for the list.

.PHONY: help start dev install build build-install push push-build

help:
	@awk 'BEGIN {FS = ":.*##"; printf "Usage:\n  make \033[36m<target>\033[0m\n\nTargets:\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

start: ## Run start.sh (sudo dev launcher — iOS 17+ ready)
	./start.sh

dev: start ## Alias for start

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
