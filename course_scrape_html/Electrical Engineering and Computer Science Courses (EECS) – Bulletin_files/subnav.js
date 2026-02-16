const subnavController = function() {
	//Get both subnavs
	const sidebarSubnav = document.querySelector(".widget-area .subnav");
	const headerSubnav = document.querySelector(".container .subnav");

	//check if the subnav holds more than one item
	//if it only holds one item, hide and do not do anything else
	let hideAll = false;

	//get all li elements in the subnav
	//(both subnavs are the same, so just use one)
	//full width page doesn't have sidebar subnav, so use header
	const liCount = headerSubnav.querySelectorAll("li");
	if (liCount.length <= 1) {
		hideAll = true;
		if (sidebarSubnav) {
			sidebarSubnav.classList.add("hide");
		}
		headerSubnav.classList.add("hide");
	}

	//If the subnav has more than one item, set up event listeners, handlers
	if (!hideAll) {
		//Get value of Bootstrap's xl breakpoint (where we need to switch the subnavs)
		const breakpointStr = window
			.getComputedStyle(document.documentElement)
			.getPropertyValue("--breakpoint-xl");
		const breakpoint = parseFloat(breakpointStr.split("px")[0]);

		//get initial window width
		let windowWidth = window.innerWidth;
		showHideSubnav(windowWidth, breakpoint);

		function showHideSubnav(windowWidth, breakpoint) {
			//Show sidebar subnav if screen is wider than xl breakpoint
			//else, show header subnav and hide sidbar subnav
			if (windowWidth <= breakpoint) {
				if (sidebarSubnav) {
					sidebarSubnav.classList.add("hide");
				}
				headerSubnav.classList.remove("hide");
			} else {
				if (sidebarSubnav) {
					sidebarSubnav.classList.remove("hide");
				}
				headerSubnav.classList.add("hide");
			}
		}

		function handleResize() {
			//update window width
			windowWidth = window.innerWidth;
			showHideSubnav(windowWidth, breakpoint);
		}

		//Listen for window resize
		window.addEventListener("resize", handleResize);

    let lowerCurrentItems = document.querySelectorAll(
			".widget-area .subnav .current-menu-item:not(.current_page_parent)"
		);
		let upperCurrentItems = document.querySelectorAll(
			"#above-content .subnav .current-menu-item:not(.current_page_parent)"
		);

		function fixCurrentMenuLinks(subNavSet) {
			$(subNavSet).each(function (i, item) {
				if (i > 0) {
					$(item).removeClass("current-menu-item");
				}
			});
		}

		fixCurrentMenuLinks(upperCurrentItems);
		fixCurrentMenuLinks(lowerCurrentItems);
	}


}();

