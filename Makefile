.PHONY: init run status export test clean help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

init: ## Initialize a run: make init DRAFT=draft.md FORMAT=blog TAG=my-post
	redpen init $(DRAFT) --format $(or $(FORMAT),blog) $(if $(TAG),--tag $(TAG),)

run: ## Run the optimization loop: make run [MAX=20]
	redpen run $(if $(MAX),--max-iterations $(MAX),)

status: ## Show run status
	redpen status

export: ## Export final draft: make export [OUTPUT=final.md]
	redpen export $(if $(OUTPUT),-o $(OUTPUT),)

test: ## Run tests
	python -m pytest tests/ -v

clean: ## Remove data directory and start fresh
	rm -rf data/
	@echo "Cleaned data/ directory"
